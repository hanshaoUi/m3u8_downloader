import asyncio
import aiohttp
import aiofiles
import os
import time
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
from asyncio_throttle import Throttler
from .m3u8_parser import M3U8Playlist, M3U8Parser


@dataclass
class DownloadProgress:
    total_segments: int
    completed_segments: int = 0
    failed_segments: int = 0
    downloaded_bytes: int = 0
    speed: float = 0.0
    eta: float = 0.0
    status: str = "waiting"  # waiting, downloading, paused, completed, failed


@dataclass
class DownloadTask:
    id: str
    url: str
    output_path: str
    filename: str
    playlist: Optional[M3U8Playlist] = None
    progress: DownloadProgress = field(default_factory=lambda: DownloadProgress(0))
    created_time: float = field(default_factory=time.time)
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class AsyncDownloader:
    def __init__(self,
                 max_concurrent: int = 8,
                 max_speed: Optional[int] = None,  # KB/s
                 timeout: int = 30,
                 retry_count: int = 3):
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.retry_count = retry_count
        self.session: Optional[aiohttp.ClientSession] = None

        # 速度限制器
        self.throttler = None
        if max_speed:
            self.throttler = Throttler(rate_limit=max_speed * 1024)  # 转换为字节/秒

        # 下载状态管理
        self.tasks: Dict[str, DownloadTask] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.paused_tasks: set = set()

        # 回调函数
        self.progress_callbacks: List[Callable] = []
        self.complete_callbacks: List[Callable] = []
        self.error_callbacks: List[Callable] = []

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def add_progress_callback(self, callback: Callable[[str, DownloadProgress], None]):
        self.progress_callbacks.append(callback)

    def add_complete_callback(self, callback: Callable[[str, DownloadTask], None]):
        self.complete_callbacks.append(callback)

    def add_error_callback(self, callback: Callable[[str, Exception], None]):
        self.error_callbacks.append(callback)

    async def add_download_task(self, task_id: str, url: str, output_path: str, filename: str) -> DownloadTask:
        """添加下载任务"""
        try:
            # 解析M3U8
            parser = M3U8Parser()
            playlist = parser.parse_m3u8(url)

            task = DownloadTask(
                id=task_id,
                url=url,
                output_path=output_path,
                filename=filename,
                playlist=playlist,
                progress=DownloadProgress(total_segments=len(playlist.segments))
            )

            self.tasks[task_id] = task
            return task

        except Exception as e:
            await self._notify_error(task_id, e)
            raise

    async def start_download(self, task_id: str):
        """开始下载任务"""
        if task_id not in self.tasks:
            raise ValueError(f"任务 {task_id} 不存在")

        if task_id in self.running_tasks:
            return  # 已在运行

        task = self.tasks[task_id]
        task.progress.status = "downloading"
        task.start_time = time.time()

        # 创建下载协程
        download_coro = self._download_task(task)
        self.running_tasks[task_id] = asyncio.create_task(download_coro)

    async def pause_download(self, task_id: str):
        """暂停下载任务"""
        if task_id in self.running_tasks:
            self.running_tasks[task_id].cancel()
            del self.running_tasks[task_id]

        self.paused_tasks.add(task_id)
        if task_id in self.tasks:
            self.tasks[task_id].progress.status = "paused"

    async def resume_download(self, task_id: str):
        """恢复下载任务"""
        self.paused_tasks.discard(task_id)
        await self.start_download(task_id)

    async def cancel_download(self, task_id: str):
        """取消下载任务"""
        if task_id in self.running_tasks:
            self.running_tasks[task_id].cancel()
            del self.running_tasks[task_id]

        if task_id in self.tasks:
            self.tasks[task_id].progress.status = "cancelled"

    async def _download_task(self, task: DownloadTask):
        """执行具体的下载任务"""
        try:
            # 创建输出目录
            output_dir = Path(task.output_path)
            temp_dir = output_dir / f"{task.filename}_temp"
            temp_dir.mkdir(parents=True, exist_ok=True)

            # 获取加密密钥（如果需要）
            encryption_key = None
            if task.playlist.is_encrypted and task.playlist.key_uri:
                parser = M3U8Parser()
                encryption_key = parser.get_encryption_key(task.playlist.key_uri)

            # 创建下载信号量
            semaphore = asyncio.Semaphore(self.max_concurrent)

            # 创建下载任务列表
            download_tasks = []
            for i, segment in enumerate(task.playlist.segments):
                if task.id in self.paused_tasks:
                    break

                segment_task = self._download_segment(
                    task, segment, i, temp_dir, encryption_key, semaphore
                )
                download_tasks.append(segment_task)

            # 等待所有片段下载完成
            results = await asyncio.gather(*download_tasks, return_exceptions=True)

            # 检查下载结果并重试失败的片段
            failed_indices = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    failed_indices.append(i)

            task.progress.failed_segments = len(failed_indices)

            # 如果有失败的片段，尝试重新下载
            if failed_indices:
                print(f"检测到 {len(failed_indices)} 个失败片段，开始重试下载...")

                # 重试失败的片段，使用较低的并发数
                retry_semaphore = asyncio.Semaphore(max(1, self.max_concurrent // 4))
                retry_tasks = []

                for index in failed_indices:
                    segment = task.playlist.segments[index]
                    task_coro = self._download_segment(
                        task, segment, index, temp_dir,
                        encryption_key, retry_semaphore
                    )
                    retry_tasks.append(task_coro)

                retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)
                final_failed = sum(1 for r in retry_results if isinstance(r, Exception))
                task.progress.failed_segments = final_failed

                if final_failed > 0:
                    print(f"重试后仍有 {final_failed} 个片段失败")

            # 决定是否完成或失败
            if task.progress.failed_segments == 0:
                # 合并视频片段
                await self._merge_segments(task, temp_dir)
                task.progress.status = "completed"
                task.end_time = time.time()

                # 清理临时文件
                await self._cleanup_temp_files(temp_dir)

                await self._notify_complete(task.id, task)
            else:
                task.progress.status = "failed"
                await self._notify_error(task.id, Exception(f"{task.progress.failed_segments} 个片段下载失败"))

        except asyncio.CancelledError:
            task.progress.status = "cancelled"
        except Exception as e:
            task.progress.status = "failed"
            await self._notify_error(task.id, e)
        finally:
            if task.id in self.running_tasks:
                del self.running_tasks[task.id]

    async def _download_segment(self, task: DownloadTask, segment, index: int,
                              temp_dir: Path, encryption_key: Optional[bytes],
                              semaphore: asyncio.Semaphore):
        """下载单个视频片段"""
        async with semaphore:
            segment_file = temp_dir / f"segment_{index:06d}.ts"

            if segment_file.exists():
                # 片段已存在，跳过
                task.progress.completed_segments += 1
                await self._notify_progress(task.id, task.progress)
                return

            for attempt in range(self.retry_count + 1):
                try:
                    async with self.session.get(segment.uri) as response:
                        response.raise_for_status()

                        content = await response.read()

                        # 解密（如果需要）
                        if encryption_key and segment.key_iv:
                            parser = M3U8Parser()
                            content = parser.decrypt_segment(content, encryption_key, segment.key_iv)

                        # 应用速度限制
                        if self.throttler:
                            await self.throttler.acquire(len(content))

                        # 保存文件
                        async with aiofiles.open(segment_file, 'wb') as f:
                            await f.write(content)

                        # 更新进度
                        task.progress.completed_segments += 1
                        task.progress.downloaded_bytes += len(content)

                        # 计算下载速度
                        if task.start_time:
                            elapsed = time.time() - task.start_time
                            if elapsed > 0:
                                task.progress.speed = task.progress.downloaded_bytes / elapsed / 1024  # KB/s

                                # 计算剩余时间
                                remaining_segments = task.progress.total_segments - task.progress.completed_segments
                                if task.progress.completed_segments > 0:
                                    avg_time_per_segment = elapsed / task.progress.completed_segments
                                    task.progress.eta = remaining_segments * avg_time_per_segment

                        await self._notify_progress(task.id, task.progress)
                        return

                except Exception as e:
                    if attempt == self.retry_count:
                        # 记录失败的片段
                        task.progress.failed_segments += 1
                        await self._notify_progress(task.id, task.progress)
                        raise e

                    # 改进的退避策略
                    from ..utils.config import get_config
                    config = get_config()
                    delay = min(config.download.retry_delay * (2 ** attempt),
                              config.download.max_retry_delay)
                    await asyncio.sleep(delay)

    async def _merge_segments(self, task: DownloadTask, temp_dir: Path):
        """合并视频片段为MP4文件"""
        output_file = Path(task.output_path) / f"{task.filename}.mp4"

        # 创建片段列表文件
        segments_list = temp_dir / "segments.txt"
        async with aiofiles.open(segments_list, 'w', encoding='utf-8') as f:
            for i in range(task.progress.total_segments):
                segment_file = temp_dir / f"segment_{i:06d}.ts"
                if segment_file.exists():
                    await f.write(f"file '{segment_file.absolute()}'\n")

        # 使用FFmpeg合并
        import subprocess

        cmd = [
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', str(segments_list),
            '-c', 'copy',
            '-y',  # 覆盖输出文件
            str(output_file)
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise Exception(f"FFmpeg合并失败: {stderr.decode()}")

    async def _cleanup_temp_files(self, temp_dir: Path):
        """清理临时文件"""
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except Exception:
            pass  # 忽略清理错误

    async def _notify_progress(self, task_id: str, progress: DownloadProgress):
        """通知进度更新"""
        for callback in self.progress_callbacks:
            try:
                callback(task_id, progress)
            except Exception:
                pass

    async def _notify_complete(self, task_id: str, task: DownloadTask):
        """通知任务完成"""
        for callback in self.complete_callbacks:
            try:
                callback(task_id, task)
            except Exception:
                pass

    async def _notify_error(self, task_id: str, error: Exception):
        """通知错误"""
        for callback in self.error_callbacks:
            try:
                callback(task_id, error)
            except Exception:
                pass

    def get_task_status(self, task_id: str) -> Optional[DownloadTask]:
        """获取任务状态"""
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> Dict[str, DownloadTask]:
        """获取所有任务"""
        return self.tasks.copy()


# 使用示例
async def main():
    async with AsyncDownloader(max_concurrent=8, max_speed=1024) as downloader:
        # 添加进度回调
        def on_progress(task_id: str, progress: DownloadProgress):
            percent = (progress.completed_segments / progress.total_segments) * 100
            print(f"任务 {task_id}: {percent:.1f}% - {progress.speed:.1f} KB/s")

        downloader.add_progress_callback(on_progress)

        # 添加下载任务
        task = await downloader.add_download_task(
            "task1",
            "https://example.com/video.m3u8",
            "./downloads",
            "video"
        )

        # 开始下载
        await downloader.start_download("task1")

        # 等待下载完成
        while task.progress.status in ["waiting", "downloading"]:
            await asyncio.sleep(1)

        print(f"下载完成: {task.progress.status}")


if __name__ == "__main__":
    asyncio.run(main())