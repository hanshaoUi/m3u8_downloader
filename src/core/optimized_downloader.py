"""
优化后的下载器 - 解决性能瓶颈和并发问题
"""

import asyncio
import aiohttp
import aiofiles
import time
from typing import List, Dict, Optional, Callable, AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import pickle
from collections import deque
import weakref
import psutil
import logging

from .m3u8_parser import M3U8Playlist, M3U8Parser


@dataclass
class SegmentInfo:
    """片段下载信息"""
    index: int
    uri: str
    file_path: Path
    size: int = 0
    checksum: Optional[str] = None
    retry_count: int = 0
    last_error: Optional[str] = None


@dataclass
class DownloadProgress:
    total_segments: int
    completed_segments: int = 0
    failed_segments: int = 0
    downloaded_bytes: int = 0
    speed: float = 0.0
    eta: float = 0.0
    status: str = "waiting"  # waiting, downloading, paused, completed, failed
    current_concurrent: int = 0  # 当前并发数


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
    segments_info: List[SegmentInfo] = field(default_factory=list)
    resume_data_file: Optional[Path] = None


class AdaptiveSpeedController:
    """自适应速度控制器"""

    def __init__(self, initial_concurrent: int = 8, max_concurrent: int = 32):
        self.current_concurrent = initial_concurrent
        self.max_concurrent = max_concurrent
        self.min_concurrent = 2

        # 性能监控
        self.speed_history = deque(maxlen=20)
        self.error_rate_history = deque(maxlen=10)
        self.last_adjustment = time.time()
        self.adjustment_interval = 10.0  # 调整间隔(秒)

    def record_performance(self, speed: float, error_rate: float):
        """记录性能数据"""
        self.speed_history.append(speed)
        self.error_rate_history.append(error_rate)

    def should_adjust(self) -> bool:
        """判断是否应该调整并发数"""
        return (time.time() - self.last_adjustment) > self.adjustment_interval

    def adjust_concurrent(self) -> int:
        """自适应调整并发数"""
        if not self.should_adjust() or len(self.speed_history) < 5:
            return self.current_concurrent

        avg_speed = sum(self.speed_history) / len(self.speed_history)
        avg_error_rate = sum(self.error_rate_history) / len(self.error_rate_history) if self.error_rate_history else 0

        # 决策逻辑
        if avg_error_rate > 0.1:  # 错误率过高，降低并发
            self.current_concurrent = max(self.min_concurrent, self.current_concurrent - 2)
        elif avg_error_rate < 0.05 and avg_speed > 0:  # 错误率低且有速度，可以提升并发
            recent_speeds = list(self.speed_history)[-5:]
            if len(recent_speeds) >= 3 and recent_speeds[-1] > recent_speeds[-3]:  # 速度呈上升趋势
                self.current_concurrent = min(self.max_concurrent, self.current_concurrent + 1)

        self.last_adjustment = time.time()
        return self.current_concurrent


class ConnectionPool:
    """连接池管理器"""

    def __init__(self, max_connections: int = 100, max_connections_per_host: int = 30):
        self.max_connections = max_connections
        self.max_connections_per_host = max_connections_per_host
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None

    async def get_session(self) -> aiohttp.ClientSession:
        """获取或创建HTTP会话"""
        if self._session is None or self._session.closed:
            self._connector = aiohttp.TCPConnector(
                limit=self.max_connections,
                limit_per_host=self.max_connections_per_host,
                ttl_dns_cache=300,  # DNS缓存5分钟
                use_dns_cache=True,
                enable_cleanup_closed=True,
                keepalive_timeout=30,
                limit_connection_pool_size=50
            )

            timeout = aiohttp.ClientTimeout(
                total=60,
                connect=10,
                sock_read=30
            )

            self._session = aiohttp.ClientSession(
                connector=self._connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )

        return self._session

    async def close(self):
        """关闭连接池"""
        if self._session and not self._session.closed:
            await self._session.close()
        if self._connector:
            await self._connector.close()


class SmartSpeedLimiter:
    """智能速度限制器"""

    def __init__(self, max_speed_kbps: Optional[int] = None):
        self.max_speed_kbps = max_speed_kbps
        self.last_update = time.time()
        self.bytes_consumed = 0
        self.speed_samples = deque(maxlen=10)

    async def acquire(self, bytes_count: int):
        """获取带宽许可"""
        if not self.max_speed_kbps:
            return

        current_time = time.time()
        time_elapsed = current_time - self.last_update

        # 计算当前速度
        if time_elapsed > 0:
            current_speed = self.bytes_consumed / time_elapsed / 1024  # KB/s
            self.speed_samples.append(current_speed)

        # 重置计数器
        if time_elapsed >= 1.0:
            self.bytes_consumed = 0
            self.last_update = current_time

        self.bytes_consumed += bytes_count

        # 如果超速了，需要等待
        max_bytes_per_second = self.max_speed_kbps * 1024
        if self.bytes_consumed > max_bytes_per_second:
            sleep_time = (self.bytes_consumed - max_bytes_per_second) / max_bytes_per_second
            if sleep_time > 0:
                await asyncio.sleep(min(sleep_time, 1.0))


class OptimizedAsyncDownloader:
    """优化后的异步下载器"""

    def __init__(self,
                 max_concurrent: int = 16,
                 max_speed_kbps: Optional[int] = None,
                 timeout: int = 30,
                 retry_count: int = 5,
                 enable_adaptive: bool = True,
                 chunk_size: int = 8192):  # 流式下载块大小

        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.retry_count = retry_count
        self.chunk_size = chunk_size
        self.enable_adaptive = enable_adaptive

        # 连接管理
        self.connection_pool = ConnectionPool()
        self.speed_limiter = SmartSpeedLimiter(max_speed_kbps)

        # 自适应控制
        if enable_adaptive:
            self.speed_controller = AdaptiveSpeedController(max_concurrent // 2, max_concurrent)
        else:
            self.speed_controller = None

        # 任务管理
        self.tasks: Dict[str, DownloadTask] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.paused_tasks: set = set()

        # 回调函数
        self.progress_callbacks: List[Callable] = []
        self.complete_callbacks: List[Callable] = []
        self.error_callbacks: List[Callable] = []

        # 统计信息
        self.stats = {
            'total_downloaded': 0,
            'total_errors': 0,
            'start_time': time.time()
        }

    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.connection_pool.close()

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
            playlist = await self._parse_m3u8_async(parser, url)

            # 创建任务目录
            task_output_path = Path(output_path)
            temp_dir = task_output_path / f"{filename}_temp"
            temp_dir.mkdir(parents=True, exist_ok=True)

            # 创建任务
            task = DownloadTask(
                id=task_id,
                url=url,
                output_path=output_path,
                filename=filename,
                playlist=playlist,
                progress=DownloadProgress(total_segments=len(playlist.segments)),
                resume_data_file=temp_dir / "resume.pkl"
            )

            # 生成片段信息
            task.segments_info = [
                SegmentInfo(
                    index=i,
                    uri=segment.uri,
                    file_path=temp_dir / f"segment_{i:06d}.ts"
                )
                for i, segment in enumerate(playlist.segments)
            ]

            # 检查断点续传
            await self._load_resume_data(task)

            self.tasks[task_id] = task
            return task

        except Exception as e:
            await self._notify_error(task_id, e)
            raise

    async def _parse_m3u8_async(self, parser: M3U8Parser, url: str) -> M3U8Playlist:
        """异步解析M3U8"""
        # 这里应该改为异步实现，当前使用同步版本
        return parser.parse_m3u8(url)

    async def _load_resume_data(self, task: DownloadTask):
        """加载断点续传数据"""
        if not task.resume_data_file.exists():
            return

        try:
            with open(task.resume_data_file, 'rb') as f:
                resume_data = pickle.load(f)

            # 验证已下载的片段
            completed_count = 0
            for segment_info in task.segments_info:
                if segment_info.file_path.exists():
                    # 验证文件完整性
                    stat = segment_info.file_path.stat()
                    if stat.st_size > 0:
                        completed_count += 1
                        task.progress.downloaded_bytes += stat.st_size

            task.progress.completed_segments = completed_count

        except Exception as e:
            logging.warning(f"加载断点续传数据失败: {e}")

    async def _save_resume_data(self, task: DownloadTask):
        """保存断点续传数据"""
        try:
            resume_data = {
                'task_id': task.id,
                'completed_segments': task.progress.completed_segments,
                'downloaded_bytes': task.progress.downloaded_bytes,
                'timestamp': time.time()
            }

            with open(task.resume_data_file, 'wb') as f:
                pickle.dump(resume_data, f)

        except Exception as e:
            logging.warning(f"保存断点续传数据失败: {e}")

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
        download_coro = self._download_task_optimized(task)
        self.running_tasks[task_id] = asyncio.create_task(download_coro)

    async def _download_task_optimized(self, task: DownloadTask):
        """优化的下载任务执行"""
        try:
            # 获取未完成的片段
            pending_segments = [
                seg for seg in task.segments_info
                if not seg.file_path.exists() or seg.file_path.stat().st_size == 0
            ]

            if not pending_segments:
                # 所有片段都已下载，直接合并
                await self._merge_segments(task)
                task.progress.status = "completed"
                await self._notify_complete(task.id, task)
                return

            # 自适应并发控制
            current_concurrent = self.max_concurrent
            if self.speed_controller:
                current_concurrent = self.speed_controller.current_concurrent
                task.progress.current_concurrent = current_concurrent

            # 创建信号量
            semaphore = asyncio.Semaphore(current_concurrent)

            # 创建下载任务
            download_tasks = []
            for segment_info in pending_segments:
                if task.id in self.paused_tasks:
                    break

                download_task = self._download_segment_optimized(
                    task, segment_info, semaphore
                )
                download_tasks.append(download_task)

            # 执行下载并收集结果
            results = await asyncio.gather(*download_tasks, return_exceptions=True)

            # 处理结果和更新统计
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            error_count = len(results) - success_count

            self.stats['total_downloaded'] += success_count
            self.stats['total_errors'] += error_count

            # 更新自适应控制器
            if self.speed_controller:
                error_rate = error_count / len(results) if results else 0
                current_speed = task.progress.speed
                self.speed_controller.record_performance(current_speed, error_rate)

            # 处理失败的片段
            failed_segments = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    failed_segments.append(pending_segments[i])

            task.progress.failed_segments = len(failed_segments)

            # 重试失败的片段
            if failed_segments and task.progress.failed_segments < len(task.segments_info) * 0.1:  # 失败率小于10%才重试
                await self._retry_failed_segments(task, failed_segments)

            # 保存进度
            await self._save_resume_data(task)

            # 判断是否完成
            if task.progress.failed_segments == 0:
                await self._merge_segments(task)
                task.progress.status = "completed"
                task.end_time = time.time()
                await self._cleanup_temp_files(task)
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

    async def _download_segment_optimized(self, task: DownloadTask, segment_info: SegmentInfo, semaphore: asyncio.Semaphore):
        """优化的片段下载"""
        async with semaphore:
            if segment_info.file_path.exists() and segment_info.file_path.stat().st_size > 0:
                # 片段已存在且非空，跳过
                return

            session = await self.connection_pool.get_session()

            for attempt in range(self.retry_count + 1):
                try:
                    async with session.get(segment_info.uri) as response:
                        response.raise_for_status()

                        # 流式下载，减少内存使用
                        total_size = 0
                        async with aiofiles.open(segment_info.file_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(self.chunk_size):
                                await f.write(chunk)
                                total_size += len(chunk)

                                # 应用速度限制
                                await self.speed_limiter.acquire(len(chunk))

                        # 更新进度
                        task.progress.completed_segments += 1
                        task.progress.downloaded_bytes += total_size
                        segment_info.size = total_size

                        # 计算速度和ETA
                        self._update_speed_and_eta(task)

                        await self._notify_progress(task.id, task.progress)
                        return

                except Exception as e:
                    segment_info.last_error = str(e)
                    segment_info.retry_count = attempt + 1

                    if attempt == self.retry_count:
                        task.progress.failed_segments += 1
                        raise e

                    # 智能重试延迟
                    delay = await self._calculate_retry_delay(e, attempt)
                    await asyncio.sleep(delay)

    async def _calculate_retry_delay(self, error: Exception, attempt: int) -> float:
        """计算智能重试延迟"""
        base_delay = 0.5

        # 根据错误类型调整延迟
        if "timeout" in str(error).lower():
            base_delay = 2.0  # 超时错误需要更长延迟
        elif "503" in str(error) or "502" in str(error):
            base_delay = 5.0  # 服务器错误需要更长延迟
        elif "429" in str(error):
            base_delay = 10.0  # 限流错误需要最长延迟

        # 指数退避 + 随机抖动
        import random
        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
        return min(delay, 30.0)  # 最大30秒

    def _update_speed_and_eta(self, task: DownloadTask):
        """更新下载速度和预计剩余时间"""
        if task.start_time:
            elapsed = time.time() - task.start_time
            if elapsed > 0:
                task.progress.speed = task.progress.downloaded_bytes / elapsed / 1024  # KB/s

                # 计算ETA
                remaining_segments = task.progress.total_segments - task.progress.completed_segments
                if task.progress.completed_segments > 0:
                    avg_time_per_segment = elapsed / task.progress.completed_segments
                    task.progress.eta = remaining_segments * avg_time_per_segment

    async def _retry_failed_segments(self, task: DownloadTask, failed_segments: List[SegmentInfo]):
        """重试失败的片段"""
        retry_semaphore = asyncio.Semaphore(max(2, self.max_concurrent // 4))
        retry_tasks = []

        for segment_info in failed_segments:
            retry_task = self._download_segment_optimized(task, segment_info, retry_semaphore)
            retry_tasks.append(retry_task)

        retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)
        final_failed = sum(1 for r in retry_results if isinstance(r, Exception))
        task.progress.failed_segments = final_failed

    async def _merge_segments(self, task: DownloadTask):
        """合并视频片段"""
        # 使用优化的视频处理器
        from .video_processor import FFmpegProcessor

        temp_dir = Path(task.output_path) / f"{task.filename}_temp"
        output_file = Path(task.output_path) / f"{task.filename}.mp4"

        processor = FFmpegProcessor()

        def merge_progress(progress: float):
            # 合并进度从90%到100%
            task.progress.status = f"merging_{progress:.1f}%"
            asyncio.create_task(self._notify_progress(task.id, task.progress))

        success = await processor.merge_ts_segments(temp_dir, output_file, merge_progress)
        if not success:
            raise Exception("视频合并失败")

    async def _cleanup_temp_files(self, task: DownloadTask):
        """清理临时文件"""
        try:
            temp_dir = Path(task.output_path) / f"{task.filename}_temp"
            if temp_dir.exists():
                import shutil
                shutil.rmtree(temp_dir)
        except Exception as e:
            logging.warning(f"清理临时文件失败: {e}")

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

    def get_download_stats(self) -> Dict:
        """获取下载统计信息"""
        elapsed = time.time() - self.stats['start_time']
        return {
            'total_downloaded': self.stats['total_downloaded'],
            'total_errors': self.stats['total_errors'],
            'uptime_seconds': elapsed,
            'average_speed': self.stats['total_downloaded'] / elapsed if elapsed > 0 else 0,
            'success_rate': self.stats['total_downloaded'] / (self.stats['total_downloaded'] + self.stats['total_errors']) if (self.stats['total_downloaded'] + self.stats['total_errors']) > 0 else 1.0
        }

    async def pause_download(self, task_id: str):
        """暂停下载"""
        if task_id in self.running_tasks:
            self.running_tasks[task_id].cancel()
            del self.running_tasks[task_id]
        self.paused_tasks.add(task_id)
        if task_id in self.tasks:
            self.tasks[task_id].progress.status = "paused"
            await self._save_resume_data(self.tasks[task_id])

    async def resume_download(self, task_id: str):
        """恢复下载"""
        self.paused_tasks.discard(task_id)
        await self.start_download(task_id)