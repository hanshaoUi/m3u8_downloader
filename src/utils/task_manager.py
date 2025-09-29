"""
全局任务管理器 - 用于GUI和HTTP服务器之间的数据同步
"""

import asyncio
import uuid
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
import threading
import queue
from enum import Enum

from ..core.downloader import AsyncDownloader, DownloadTask, DownloadProgress


class TaskEvent(Enum):
    TASK_ADDED = "task_added"
    TASK_STARTED = "task_started"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_PAUSED = "task_paused"
    TASK_RESUMED = "task_resumed"
    LOG_MESSAGE = "log_message"


@dataclass
class TaskEventData:
    event_type: TaskEvent
    task_id: str
    data: Dict = None
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class GlobalTaskManager:
    """全局任务管理器，负责协调GUI和HTTP服务器之间的任务状态"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self.tasks: Dict[str, DownloadTask] = {}
        self.downloader: Optional[AsyncDownloader] = None
        self.event_queue = queue.Queue()
        self.callbacks: Dict[TaskEvent, List[Callable]] = {event: [] for event in TaskEvent}

        # 线程安全锁
        self.tasks_lock = threading.RLock()
        self.downloader_lock = threading.RLock()

        # 事件处理线程
        self.event_thread = None
        self.running = False

    def start(self):
        """启动任务管理器"""
        if not self.running:
            self.running = True
            self.event_thread = threading.Thread(target=self._event_processor, daemon=True)
            self.event_thread.start()

    def stop(self):
        """停止任务管理器"""
        self.running = False
        if self.event_thread:
            self.event_thread.join(timeout=5)

    def _event_processor(self):
        """事件处理线程"""
        while self.running:
            try:
                event_data = self.event_queue.get(timeout=1)
                self._dispatch_event(event_data)
                self.event_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"事件处理错误: {e}")

    def _dispatch_event(self, event_data: TaskEventData):
        """分发事件到注册的回调函数"""
        callbacks = self.callbacks.get(event_data.event_type, [])
        for callback in callbacks:
            try:
                callback(event_data)
            except Exception as e:
                print(f"回调函数执行错误: {e}")

    def add_callback(self, event_type: TaskEvent, callback: Callable):
        """添加事件回调"""
        if event_type not in self.callbacks:
            self.callbacks[event_type] = []
        self.callbacks[event_type].append(callback)

    def remove_callback(self, event_type: TaskEvent, callback: Callable):
        """移除事件回调"""
        if event_type in self.callbacks and callback in self.callbacks[event_type]:
            self.callbacks[event_type].remove(callback)

    async def get_or_create_downloader(self) -> AsyncDownloader:
        """获取或创建下载器实例"""
        with self.downloader_lock:
            if self.downloader is None:
                from ..utils.config import get_config
                config = get_config()

                self.downloader = AsyncDownloader(
                    max_concurrent=config.download.max_concurrent,
                    max_speed=config.download.max_speed_kbps,
                    timeout=config.download.timeout,
                    retry_count=config.download.retry_count
                )

                await self.downloader.__aenter__()

                # 设置回调
                self.downloader.add_progress_callback(self._on_progress)
                self.downloader.add_complete_callback(self._on_complete)
                self.downloader.add_error_callback(self._on_error)

            return self.downloader

    def _on_progress(self, task_id: str, progress: DownloadProgress):
        """下载进度回调"""
        with self.tasks_lock:
            if task_id in self.tasks:
                self.tasks[task_id].progress = progress

        event_data = TaskEventData(
            event_type=TaskEvent.TASK_PROGRESS,
            task_id=task_id,
            data={
                'total_segments': progress.total_segments,
                'completed_segments': progress.completed_segments,
                'failed_segments': progress.failed_segments,
                'speed': progress.speed,
                'eta': progress.eta,
                'status': progress.status
            }
        )
        self.event_queue.put(event_data)

    def _on_complete(self, task_id: str, task: DownloadTask):
        """下载完成回调"""
        with self.tasks_lock:
            if task_id in self.tasks:
                self.tasks[task_id] = task

        event_data = TaskEventData(
            event_type=TaskEvent.TASK_COMPLETED,
            task_id=task_id,
            data={
                'filename': task.filename,
                'output_path': task.output_path
            }
        )
        self.event_queue.put(event_data)

        # 发送日志消息
        self.log_message(f"下载完成: {task.filename}")

    def _on_error(self, task_id: str, error: Exception):
        """下载错误回调"""
        event_data = TaskEventData(
            event_type=TaskEvent.TASK_FAILED,
            task_id=task_id,
            data={'error': str(error)}
        )
        self.event_queue.put(event_data)

        # 发送日志消息
        self.log_message(f"下载失败: {task_id} - {error}")

    async def add_download_task(self, url: str, output_path: str, filename: str) -> str:
        """添加下载任务"""
        task_id = str(uuid.uuid4())

        downloader = await self.get_or_create_downloader()
        task = await downloader.add_download_task(task_id, url, output_path, filename)

        with self.tasks_lock:
            self.tasks[task_id] = task

        # 发送任务添加事件
        event_data = TaskEventData(
            event_type=TaskEvent.TASK_ADDED,
            task_id=task_id,
            data={
                'url': url,
                'filename': filename,
                'output_path': output_path
            }
        )
        self.event_queue.put(event_data)

        # 发送日志消息
        self.log_message(f"添加下载任务: {filename}")

        return task_id

    async def start_download(self, task_id: str):
        """开始下载"""
        downloader = await self.get_or_create_downloader()
        await downloader.start_download(task_id)

        event_data = TaskEventData(
            event_type=TaskEvent.TASK_STARTED,
            task_id=task_id
        )
        self.event_queue.put(event_data)

        self.log_message(f"开始下载: {task_id}")

    async def pause_download(self, task_id: str):
        """暂停下载"""
        if self.downloader:
            await self.downloader.pause_download(task_id)

        event_data = TaskEventData(
            event_type=TaskEvent.TASK_PAUSED,
            task_id=task_id
        )
        self.event_queue.put(event_data)

        self.log_message(f"暂停下载: {task_id}")

    async def resume_download(self, task_id: str):
        """恢复下载"""
        if self.downloader:
            await self.downloader.resume_download(task_id)

        event_data = TaskEventData(
            event_type=TaskEvent.TASK_RESUMED,
            task_id=task_id
        )
        self.event_queue.put(event_data)

        self.log_message(f"恢复下载: {task_id}")

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """获取任务信息"""
        with self.tasks_lock:
            return self.tasks.get(task_id)

    def get_all_tasks(self) -> Dict[str, DownloadTask]:
        """获取所有任务"""
        with self.tasks_lock:
            return self.tasks.copy()

    def log_message(self, message: str, level: str = "INFO"):
        """发送日志消息"""
        event_data = TaskEventData(
            event_type=TaskEvent.LOG_MESSAGE,
            task_id="",
            data={
                'message': message,
                'level': level
            }
        )
        self.event_queue.put(event_data)

    def get_task_summary(self) -> Dict:
        """获取任务摘要"""
        with self.tasks_lock:
            total = len(self.tasks)
            completed = sum(1 for task in self.tasks.values()
                          if task.progress.status == "completed")
            downloading = sum(1 for task in self.tasks.values()
                            if task.progress.status == "downloading")
            failed = sum(1 for task in self.tasks.values()
                       if task.progress.status == "failed")

            return {
                'total': total,
                'completed': completed,
                'downloading': downloading,
                'failed': failed,
                'pending': total - completed - downloading - failed
            }

    async def cancel_download(self, task_id: str):
        """取消下载任务"""
        if self.downloader:
            await self.downloader.cancel_download(task_id)

        event_data = TaskEventData(
            event_type=TaskEvent.TASK_PAUSED,
            task_id=task_id,
            data={'reason': 'cancelled'}
        )
        self.event_queue.put(event_data)

        self.log_message(f"取消下载: {task_id}")

    async def delete_task(self, task_id: str, delete_temp_files: bool = False):
        """删除任务"""
        task = None
        with self.tasks_lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                del self.tasks[task_id]

        # 先停止下载
        if task and task.progress.status == "downloading":
            await self.cancel_download(task_id)

        # 删除临时文件和完成的视频文件
        if delete_temp_files and task:
            import shutil
            from pathlib import Path

            try:
                # 删除正确的temp目录（与下载器一致）
                temp_dir = Path(task.output_path) / f"{task.filename}_temp"
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                    self.log_message(f"已删除临时文件夹: {temp_dir}")

                # 删除已完成的MP4文件
                output_file = Path(task.output_path) / f"{task.filename}.mp4"
                if output_file.exists():
                    output_file.unlink()
                    self.log_message(f"已删除视频文件: {output_file}")

                # 删除其他可能的文件格式
                for ext in ['.ts', '.m4v', '.mkv']:
                    alt_file = Path(task.output_path) / f"{task.filename}{ext}"
                    if alt_file.exists():
                        alt_file.unlink()
                        self.log_message(f"已删除文件: {alt_file}")

            except Exception as e:
                self.log_message(f"删除文件失败: {e}")
                import traceback
                self.log_message(f"错误详情: {traceback.format_exc()}")

        self.log_message(f"任务已删除: {task_id}")


# 全局实例
task_manager = GlobalTaskManager()


def get_task_manager() -> GlobalTaskManager:
    """获取全局任务管理器实例"""
    return task_manager


# 使用示例
async def example_usage():
    manager = get_task_manager()
    manager.start()

    # 添加回调
    def on_task_progress(event_data: TaskEventData):
        print(f"任务进度更新: {event_data.task_id} - {event_data.data}")

    def on_log_message(event_data: TaskEventData):
        print(f"日志: {event_data.data['message']}")

    manager.add_callback(TaskEvent.TASK_PROGRESS, on_task_progress)
    manager.add_callback(TaskEvent.LOG_MESSAGE, on_log_message)

    # 添加任务
    task_id = await manager.add_download_task(
        "https://example.com/video.m3u8",
        "./downloads",
        "test_video"
    )

    # 开始下载
    await manager.start_download(task_id)

    print("任务管理器示例运行完成")


if __name__ == "__main__":
    asyncio.run(example_usage())