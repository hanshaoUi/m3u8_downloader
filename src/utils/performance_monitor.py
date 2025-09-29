"""
性能监控模块 - 监控下载器性能指标
"""

import time
import threading
import asyncio
import psutil
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from collections import deque
import json
from pathlib import Path
import weakref

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server, CollectorRegistry
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    # 创建模拟的 Prometheus 类
    class MockMetric:
        def inc(self, *args, **kwargs): pass
        def observe(self, *args, **kwargs): pass
        def set(self, *args, **kwargs): pass

    Counter = Histogram = Gauge = lambda *args, **kwargs: MockMetric()


@dataclass
class PerformanceMetrics:
    """性能指标数据"""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_rss_mb: float
    download_speed_kbps: float
    active_connections: int
    completed_downloads: int
    failed_downloads: int
    queue_size: int
    response_time_ms: float


@dataclass
class DownloadSession:
    """下载会话统计"""
    session_id: str
    start_time: float
    end_time: Optional[float] = None
    total_bytes: int = 0
    total_segments: int = 0
    completed_segments: int = 0
    failed_segments: int = 0
    average_speed: float = 0.0
    peak_speed: float = 0.0
    concurrent_connections: int = 0


class MetricsCollector:
    """指标收集器"""

    def __init__(self, enable_prometheus: bool = True):
        self.enable_prometheus = enable_prometheus and PROMETHEUS_AVAILABLE
        self.registry = CollectorRegistry() if self.enable_prometheus else None

        # Prometheus 指标
        if self.enable_prometheus:
            self.download_counter = Counter(
                'm3u8_downloads_total',
                'Total number of downloads',
                ['status'],  # success, failed, cancelled
                registry=self.registry
            )

            self.download_duration = Histogram(
                'm3u8_download_duration_seconds',
                'Time spent downloading',
                ['task_type'],
                registry=self.registry
            )

            self.download_speed = Histogram(
                'm3u8_download_speed_kbps',
                'Download speed in KB/s',
                registry=self.registry
            )

            self.active_downloads = Gauge(
                'm3u8_active_downloads',
                'Number of active downloads',
                registry=self.registry
            )

            self.memory_usage = Gauge(
                'm3u8_memory_usage_mb',
                'Memory usage in MB',
                registry=self.registry
            )

            self.cpu_usage = Gauge(
                'm3u8_cpu_usage_percent',
                'CPU usage percentage',
                registry=self.registry
            )

            self.error_counter = Counter(
                'm3u8_errors_total',
                'Total number of errors',
                ['error_type'],
                registry=self.registry
            )

    def record_download_start(self, task_type: str = "segment"):
        """记录下载开始"""
        if self.enable_prometheus:
            self.active_downloads.inc()

    def record_download_complete(self, status: str, duration: float, speed: float, task_type: str = "segment"):
        """记录下载完成"""
        if self.enable_prometheus:
            self.download_counter.labels(status=status).inc()
            self.download_duration.labels(task_type=task_type).observe(duration)
            self.download_speed.observe(speed)
            self.active_downloads.dec()

    def record_error(self, error_type: str):
        """记录错误"""
        if self.enable_prometheus:
            self.error_counter.labels(error_type=error_type).inc()

    def update_system_metrics(self, cpu_percent: float, memory_mb: float):
        """更新系统指标"""
        if self.enable_prometheus:
            self.cpu_usage.set(cpu_percent)
            self.memory_usage.set(memory_mb)


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self,
                 history_size: int = 1000,
                 collection_interval: float = 1.0,
                 enable_prometheus: bool = True,
                 prometheus_port: int = 8000):

        self.history_size = history_size
        self.collection_interval = collection_interval
        self.enable_prometheus = enable_prometheus
        self.prometheus_port = prometheus_port

        # 数据存储
        self.metrics_history = deque(maxlen=history_size)
        self.download_sessions: Dict[str, DownloadSession] = {}
        self.active_sessions = set()

        # 指标收集器
        self.metrics_collector = MetricsCollector(enable_prometheus)

        # 监控状态
        self.monitoring = False
        self.monitor_task: Optional[asyncio.Task] = None
        self.prometheus_server = None

        # 回调函数
        self.alert_callbacks: List[Callable[[Dict], None]] = []

        # 阈值设置
        self.alert_thresholds = {
            'cpu_percent': 80.0,
            'memory_percent': 90.0,
            'error_rate': 0.1,
            'slow_download_threshold': 100.0  # KB/s
        }

        self.logger = logging.getLogger(__name__)

    async def start_monitoring(self):
        """开始监控"""
        if self.monitoring:
            return

        self.monitoring = True

        # 启动 Prometheus 服务器
        if self.enable_prometheus and PROMETHEUS_AVAILABLE:
            try:
                self.prometheus_server = start_http_server(
                    self.prometheus_port,
                    registry=self.metrics_collector.registry
                )
                self.logger.info(f"Prometheus metrics server started on port {self.prometheus_port}")
            except Exception as e:
                self.logger.warning(f"Failed to start Prometheus server: {e}")

        # 启动监控任务
        self.monitor_task = asyncio.create_task(self._monitoring_loop())
        self.logger.info("Performance monitoring started")

    async def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False

        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        if self.prometheus_server:
            self.prometheus_server.shutdown()

        self.logger.info("Performance monitoring stopped")

    async def _monitoring_loop(self):
        """监控循环"""
        while self.monitoring:
            try:
                await self._collect_metrics()
                await asyncio.sleep(self.collection_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(self.collection_interval)

    async def _collect_metrics(self):
        """收集性能指标"""
        current_time = time.time()

        # 系统指标
        process = psutil.Process()
        cpu_percent = process.cpu_percent()
        memory_info = process.memory_info()
        memory_percent = process.memory_percent()
        memory_rss_mb = memory_info.rss / 1024 / 1024

        # 下载指标
        download_speed = self._calculate_current_download_speed()
        active_connections = len(self.active_sessions)
        completed_downloads = sum(1 for s in self.download_sessions.values() if s.end_time is not None)
        failed_downloads = sum(1 for s in self.download_sessions.values() if s.failed_segments > 0)
        queue_size = len(self.active_sessions)
        response_time = self._calculate_average_response_time()

        # 创建指标记录
        metrics = PerformanceMetrics(
            timestamp=current_time,
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            memory_rss_mb=memory_rss_mb,
            download_speed_kbps=download_speed,
            active_connections=active_connections,
            completed_downloads=completed_downloads,
            failed_downloads=failed_downloads,
            queue_size=queue_size,
            response_time_ms=response_time
        )

        # 存储指标
        self.metrics_history.append(metrics)

        # 更新 Prometheus 指标
        self.metrics_collector.update_system_metrics(cpu_percent, memory_rss_mb)

        # 检查告警
        await self._check_alerts(metrics)

    def _calculate_current_download_speed(self) -> float:
        """计算当前下载速度"""
        current_time = time.time()
        total_speed = 0.0
        active_count = 0

        for session in self.download_sessions.values():
            if session.session_id in self.active_sessions and session.end_time is None:
                # 计算当前会话速度
                if current_time > session.start_time:
                    session_speed = session.total_bytes / (current_time - session.start_time) / 1024
                    total_speed += session_speed
                    active_count += 1

        return total_speed

    def _calculate_average_response_time(self) -> float:
        """计算平均响应时间"""
        if len(self.metrics_history) < 2:
            return 0.0

        recent_metrics = list(self.metrics_history)[-10:]  # 最近10个指标
        response_times = [m.response_time_ms for m in recent_metrics if m.response_time_ms > 0]

        if response_times:
            return sum(response_times) / len(response_times)
        return 0.0

    async def _check_alerts(self, metrics: PerformanceMetrics):
        """检查告警条件"""
        alerts = []

        # CPU 使用率告警
        if metrics.cpu_percent > self.alert_thresholds['cpu_percent']:
            alerts.append({
                'type': 'high_cpu',
                'message': f"CPU usage is {metrics.cpu_percent:.1f}%",
                'severity': 'warning',
                'value': metrics.cpu_percent,
                'threshold': self.alert_thresholds['cpu_percent']
            })

        # 内存使用率告警
        if metrics.memory_percent > self.alert_thresholds['memory_percent']:
            alerts.append({
                'type': 'high_memory',
                'message': f"Memory usage is {metrics.memory_percent:.1f}%",
                'severity': 'critical',
                'value': metrics.memory_percent,
                'threshold': self.alert_thresholds['memory_percent']
            })

        # 下载速度告警
        if (metrics.active_connections > 0 and
            metrics.download_speed_kbps < self.alert_thresholds['slow_download_threshold']):
            alerts.append({
                'type': 'slow_download',
                'message': f"Download speed is {metrics.download_speed_kbps:.1f} KB/s",
                'severity': 'warning',
                'value': metrics.download_speed_kbps,
                'threshold': self.alert_thresholds['slow_download_threshold']
            })

        # 错误率告警
        if len(self.download_sessions) > 10:  # 只有足够样本时才检查
            error_rate = metrics.failed_downloads / len(self.download_sessions)
            if error_rate > self.alert_thresholds['error_rate']:
                alerts.append({
                    'type': 'high_error_rate',
                    'message': f"Error rate is {error_rate:.1%}",
                    'severity': 'critical',
                    'value': error_rate,
                    'threshold': self.alert_thresholds['error_rate']
                })

        # 触发告警回调
        for alert in alerts:
            for callback in self.alert_callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    self.logger.error(f"Error in alert callback: {e}")

    def start_download_session(self, session_id: str, total_segments: int = 0) -> DownloadSession:
        """开始下载会话"""
        session = DownloadSession(
            session_id=session_id,
            start_time=time.time(),
            total_segments=total_segments
        )

        self.download_sessions[session_id] = session
        self.active_sessions.add(session_id)

        # 记录 Prometheus 指标
        self.metrics_collector.record_download_start()

        return session

    def update_download_session(self,
                              session_id: str,
                              bytes_downloaded: int = 0,
                              segments_completed: int = 0,
                              segments_failed: int = 0,
                              current_speed: float = 0.0):
        """更新下载会话"""
        if session_id not in self.download_sessions:
            return

        session = self.download_sessions[session_id]
        session.total_bytes += bytes_downloaded
        session.completed_segments += segments_completed
        session.failed_segments += segments_failed

        if current_speed > session.peak_speed:
            session.peak_speed = current_speed

        # 计算平均速度
        elapsed_time = time.time() - session.start_time
        if elapsed_time > 0:
            session.average_speed = session.total_bytes / elapsed_time / 1024

    def end_download_session(self, session_id: str, status: str = "completed"):
        """结束下载会话"""
        if session_id not in self.download_sessions:
            return

        session = self.download_sessions[session_id]
        session.end_time = time.time()

        self.active_sessions.discard(session_id)

        # 计算总耗时和平均速度
        duration = session.end_time - session.start_time
        if duration > 0:
            session.average_speed = session.total_bytes / duration / 1024

        # 记录 Prometheus 指标
        self.metrics_collector.record_download_complete(
            status=status,
            duration=duration,
            speed=session.average_speed
        )

    def add_alert_callback(self, callback: Callable[[Dict], None]):
        """添加告警回调"""
        self.alert_callbacks.append(callback)

    def get_performance_summary(self, minutes: int = 5) -> Dict[str, Any]:
        """获取性能摘要"""
        if not self.metrics_history:
            return {}

        # 获取指定时间范围内的指标
        cutoff_time = time.time() - (minutes * 60)
        recent_metrics = [m for m in self.metrics_history if m.timestamp > cutoff_time]

        if not recent_metrics:
            recent_metrics = list(self.metrics_history)[-10:]  # 至少取最近10个

        if not recent_metrics:
            return {}

        # 计算统计信息
        cpu_values = [m.cpu_percent for m in recent_metrics]
        memory_values = [m.memory_percent for m in recent_metrics]
        speed_values = [m.download_speed_kbps for m in recent_metrics if m.download_speed_kbps > 0]

        summary = {
            'time_range_minutes': minutes,
            'sample_count': len(recent_metrics),
            'cpu_usage': {
                'current': recent_metrics[-1].cpu_percent,
                'average': sum(cpu_values) / len(cpu_values),
                'peak': max(cpu_values),
                'min': min(cpu_values)
            },
            'memory_usage': {
                'current': recent_metrics[-1].memory_percent,
                'current_mb': recent_metrics[-1].memory_rss_mb,
                'average': sum(memory_values) / len(memory_values),
                'peak': max(memory_values)
            },
            'download_performance': {
                'current_speed_kbps': recent_metrics[-1].download_speed_kbps,
                'average_speed_kbps': sum(speed_values) / len(speed_values) if speed_values else 0,
                'peak_speed_kbps': max(speed_values) if speed_values else 0,
                'active_connections': recent_metrics[-1].active_connections
            },
            'session_statistics': {
                'total_sessions': len(self.download_sessions),
                'active_sessions': len(self.active_sessions),
                'completed_sessions': sum(1 for s in self.download_sessions.values() if s.end_time is not None),
                'failed_sessions': sum(1 for s in self.download_sessions.values() if s.failed_segments > 0)
            }
        }

        return summary

    def export_metrics_to_file(self, filepath: str, format: str = "json"):
        """导出指标到文件"""
        try:
            data = {
                'export_time': time.time(),
                'performance_summary': self.get_performance_summary(60),  # 最近1小时
                'metrics_history': [
                    {
                        'timestamp': m.timestamp,
                        'cpu_percent': m.cpu_percent,
                        'memory_percent': m.memory_percent,
                        'download_speed_kbps': m.download_speed_kbps,
                        'active_connections': m.active_connections
                    }
                    for m in self.metrics_history
                ],
                'download_sessions': [
                    {
                        'session_id': s.session_id,
                        'start_time': s.start_time,
                        'end_time': s.end_time,
                        'total_bytes': s.total_bytes,
                        'average_speed': s.average_speed,
                        'completed_segments': s.completed_segments,
                        'failed_segments': s.failed_segments
                    }
                    for s in self.download_sessions.values()
                ]
            }

            if format.lower() == "json":
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                raise ValueError(f"Unsupported format: {format}")

            self.logger.info(f"Metrics exported to {filepath}")

        except Exception as e:
            self.logger.error(f"Failed to export metrics: {e}")
            raise


# 全局性能监控器实例
_performance_monitor = None


def get_performance_monitor() -> PerformanceMonitor:
    """获取全局性能监控器"""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor


# 装饰器
def monitor_performance(session_id: str = None):
    """性能监控装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            monitor = get_performance_monitor()

            # 生成会话ID
            actual_session_id = session_id or f"{func.__name__}_{int(time.time())}"

            # 开始监控
            session = monitor.start_download_session(actual_session_id)
            start_time = time.time()

            try:
                result = await func(*args, **kwargs)

                # 成功完成
                monitor.end_download_session(actual_session_id, "completed")
                return result

            except Exception as e:
                # 失败
                monitor.end_download_session(actual_session_id, "failed")
                monitor.metrics_collector.record_error(type(e).__name__)
                raise

        return wrapper
    return decorator


if __name__ == "__main__":
    # 测试性能监控
    async def test_performance_monitor():
        monitor = get_performance_monitor()

        # 添加告警回调
        def alert_handler(alert):
            print(f"ALERT: {alert['type']} - {alert['message']}")

        monitor.add_alert_callback(alert_handler)

        # 启动监控
        await monitor.start_monitoring()

        # 模拟下载会话
        session1 = monitor.start_download_session("test_download_1", 100)

        # 模拟下载进度
        for i in range(10):
            await asyncio.sleep(0.1)
            monitor.update_download_session(
                "test_download_1",
                bytes_downloaded=1024 * 100,  # 100KB
                segments_completed=10,
                current_speed=1000.0  # 1MB/s
            )

        # 完成下载
        monitor.end_download_session("test_download_1", "completed")

        # 等待几秒收集指标
        await asyncio.sleep(3)

        # 获取性能摘要
        summary = monitor.get_performance_summary()
        print(f"Performance Summary: {json.dumps(summary, indent=2, ensure_ascii=False)}")

        # 导出指标
        monitor.export_metrics_to_file("performance_metrics.json")

        # 停止监控
        await monitor.stop_monitoring()

    asyncio.run(test_performance_monitor())