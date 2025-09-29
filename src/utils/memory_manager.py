"""
内存管理器 - 优化内存使用和监控
"""

import psutil
import gc
import weakref
import threading
import time
import logging
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from collections import deque
import asyncio


@dataclass
class MemoryStats:
    """内存统计信息"""
    total_memory: int
    available_memory: int
    used_memory: int
    memory_percent: float
    process_memory: int
    process_memory_percent: float


class MemoryMonitor:
    """内存监控器"""

    def __init__(self,
                 warning_threshold: float = 80.0,  # 警告阈值(%)
                 critical_threshold: float = 90.0,  # 危险阈值(%)
                 check_interval: float = 5.0):  # 检查间隔(秒)

        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.check_interval = check_interval

        self.callbacks: List[Callable[[MemoryStats], None]] = []
        self.history = deque(maxlen=100)  # 保存最近100次的内存状态

        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger(__name__)

    def add_callback(self, callback: Callable[[MemoryStats], None]):
        """添加内存状态变化回调"""
        self.callbacks.append(callback)

    def get_memory_stats(self) -> MemoryStats:
        """获取当前内存统计"""
        # 系统内存
        system_memory = psutil.virtual_memory()

        # 当前进程内存
        process = psutil.Process()
        process_memory = process.memory_info()

        stats = MemoryStats(
            total_memory=system_memory.total,
            available_memory=system_memory.available,
            used_memory=system_memory.used,
            memory_percent=system_memory.percent,
            process_memory=process_memory.rss,
            process_memory_percent=(process_memory.rss / system_memory.total) * 100
        )

        return stats

    async def start_monitoring(self):
        """开始监控"""
        if self._monitoring:
            return

        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self.logger.info("内存监控已启动")

    async def stop_monitoring(self):
        """停止监控"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self.logger.info("内存监控已停止")

    async def _monitor_loop(self):
        """监控循环"""
        while self._monitoring:
            try:
                stats = self.get_memory_stats()
                self.history.append(stats)

                # 检查阈值
                if stats.memory_percent > self.critical_threshold:
                    self.logger.critical(f"内存使用率达到危险水平: {stats.memory_percent:.1f}%")
                    await self._handle_critical_memory(stats)
                elif stats.memory_percent > self.warning_threshold:
                    self.logger.warning(f"内存使用率较高: {stats.memory_percent:.1f}%")

                # 通知回调
                for callback in self.callbacks:
                    try:
                        callback(stats)
                    except Exception as e:
                        self.logger.error(f"内存监控回调执行失败: {e}")

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                self.logger.error(f"内存监控出错: {e}")
                await asyncio.sleep(self.check_interval)

    async def _handle_critical_memory(self, stats: MemoryStats):
        """处理危险内存状态"""
        self.logger.warning("执行紧急内存清理...")

        # 强制垃圾回收
        gc.collect()

        # 等待一段时间后重新检查
        await asyncio.sleep(2)
        new_stats = self.get_memory_stats()

        improvement = stats.memory_percent - new_stats.memory_percent
        self.logger.info(f"内存清理完成，内存使用率降低了 {improvement:.1f}%")

    def get_memory_trend(self, minutes: int = 5) -> Dict:
        """获取内存使用趋势"""
        if len(self.history) < 2:
            return {"trend": "unknown", "average_usage": 0}

        # 获取指定时间内的数据
        recent_count = min(len(self.history), (minutes * 60) // self.check_interval)
        recent_data = list(self.history)[-recent_count:]

        if len(recent_data) < 2:
            return {"trend": "unknown", "average_usage": recent_data[0].memory_percent if recent_data else 0}

        # 计算趋势
        first_half = recent_data[:len(recent_data)//2]
        second_half = recent_data[len(recent_data)//2:]

        first_avg = sum(s.memory_percent for s in first_half) / len(first_half)
        second_avg = sum(s.memory_percent for s in second_half) / len(second_half)

        if second_avg > first_avg + 5:
            trend = "increasing"
        elif second_avg < first_avg - 5:
            trend = "decreasing"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "average_usage": sum(s.memory_percent for s in recent_data) / len(recent_data),
            "peak_usage": max(s.memory_percent for s in recent_data),
            "min_usage": min(s.memory_percent for s in recent_data)
        }


class ObjectPool:
    """对象池 - 重用对象减少内存分配"""

    def __init__(self, factory_func: Callable, max_size: int = 100):
        self.factory_func = factory_func
        self.max_size = max_size
        self.pool = deque()
        self.created_count = 0
        self.reused_count = 0
        self._lock = threading.Lock()

    def acquire(self):
        """获取对象"""
        with self._lock:
            if self.pool:
                obj = self.pool.popleft()
                self.reused_count += 1
                return obj
            else:
                obj = self.factory_func()
                self.created_count += 1
                return obj

    def release(self, obj):
        """释放对象回池中"""
        with self._lock:
            if len(self.pool) < self.max_size:
                # 重置对象状态（如果需要）
                if hasattr(obj, 'reset'):
                    obj.reset()
                self.pool.append(obj)

    def get_stats(self) -> Dict:
        """获取池统计信息"""
        with self._lock:
            return {
                "pool_size": len(self.pool),
                "created_count": self.created_count,
                "reused_count": self.reused_count,
                "efficiency": self.reused_count / (self.created_count + self.reused_count) if (self.created_count + self.reused_count) > 0 else 0
            }


class MemoryCache:
    """内存缓存 - 带LRU淘汰策略"""

    def __init__(self, max_size: int = 1000, max_memory_mb: int = 100):
        self.max_size = max_size
        self.max_memory_bytes = max_memory_mb * 1024 * 1024

        self.cache: Dict = {}
        self.access_order = deque()  # LRU顺序
        self.current_memory = 0
        self._lock = threading.RLock()

    def get(self, key, default=None):
        """获取缓存项"""
        with self._lock:
            if key in self.cache:
                # 更新访问顺序
                self.access_order.remove(key)
                self.access_order.append(key)
                return self.cache[key]['value']
            return default

    def set(self, key, value):
        """设置缓存项"""
        with self._lock:
            # 计算对象大小（简化估算）
            obj_size = self._estimate_size(value)

            # 如果key已存在，先移除旧值
            if key in self.cache:
                old_size = self.cache[key]['size']
                self.current_memory -= old_size
                self.access_order.remove(key)

            # 检查是否需要淘汰
            while (len(self.cache) >= self.max_size or
                   self.current_memory + obj_size > self.max_memory_bytes) and self.cache:
                self._evict_lru()

            # 添加新项
            self.cache[key] = {'value': value, 'size': obj_size, 'timestamp': time.time()}
            self.access_order.append(key)
            self.current_memory += obj_size

    def _estimate_size(self, obj) -> int:
        """估算对象大小"""
        import sys

        if isinstance(obj, (str, bytes)):
            return len(obj)
        elif isinstance(obj, (list, tuple)):
            return sum(self._estimate_size(item) for item in obj)
        elif isinstance(obj, dict):
            return sum(self._estimate_size(k) + self._estimate_size(v) for k, v in obj.items())
        else:
            return sys.getsizeof(obj)

    def _evict_lru(self):
        """淘汰最近最少使用的项"""
        if not self.access_order:
            return

        lru_key = self.access_order.popleft()
        if lru_key in self.cache:
            self.current_memory -= self.cache[lru_key]['size']
            del self.cache[lru_key]

    def clear(self):
        """清空缓存"""
        with self._lock:
            self.cache.clear()
            self.access_order.clear()
            self.current_memory = 0

    def get_stats(self) -> Dict:
        """获取缓存统计"""
        with self._lock:
            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "memory_usage_mb": self.current_memory / (1024 * 1024),
                "max_memory_mb": self.max_memory_bytes / (1024 * 1024),
                "memory_efficiency": self.current_memory / self.max_memory_bytes if self.max_memory_bytes > 0 else 0
            }


class SmartGarbageCollector:
    """智能垃圾收集器"""

    def __init__(self,
                 auto_gc_threshold: float = 85.0,  # 自动GC阈值
                 force_gc_threshold: float = 95.0):  # 强制GC阈值

        self.auto_gc_threshold = auto_gc_threshold
        self.force_gc_threshold = force_gc_threshold
        self.last_gc_time = time.time()
        self.gc_count = 0
        self.logger = logging.getLogger(__name__)

    def check_and_collect(self, memory_percent: float) -> bool:
        """检查并执行垃圾收集"""
        current_time = time.time()

        # 强制GC条件
        if memory_percent > self.force_gc_threshold:
            self.logger.warning(f"内存使用率过高({memory_percent:.1f}%)，执行强制GC")
            return self._force_gc()

        # 自动GC条件
        if (memory_percent > self.auto_gc_threshold and
            current_time - self.last_gc_time > 30):  # 至少间隔30秒
            self.logger.info(f"内存使用率较高({memory_percent:.1f}%)，执行自动GC")
            return self._auto_gc()

        return False

    def _auto_gc(self) -> bool:
        """自动垃圾收集"""
        before_memory = psutil.virtual_memory().percent

        # 执行GC
        collected = gc.collect()

        after_memory = psutil.virtual_memory().percent
        improvement = before_memory - after_memory

        self.last_gc_time = time.time()
        self.gc_count += 1

        self.logger.info(f"GC完成: 回收了{collected}个对象，内存使用率降低{improvement:.1f}%")
        return improvement > 1.0  # 改善超过1%认为有效

    def _force_gc(self) -> bool:
        """强制垃圾收集"""
        before_memory = psutil.virtual_memory().percent

        # 执行多轮GC
        total_collected = 0
        for generation in range(3):
            collected = gc.collect(generation)
            total_collected += collected

        # 清理循环引用
        gc.collect()

        after_memory = psutil.virtual_memory().percent
        improvement = before_memory - after_memory

        self.last_gc_time = time.time()
        self.gc_count += 1

        self.logger.warning(f"强制GC完成: 回收了{total_collected}个对象，内存使用率降低{improvement:.1f}%")
        return True

    def get_gc_stats(self) -> Dict:
        """获取GC统计信息"""
        gc_stats = gc.get_stats()
        return {
            "gc_count": self.gc_count,
            "last_gc_time": self.last_gc_time,
            "gc_generations": len(gc_stats),
            "gc_thresholds": gc.get_threshold(),
            "gc_counts": gc.get_count()
        }


class MemoryManager:
    """综合内存管理器"""

    def __init__(self):
        self.monitor = MemoryMonitor()
        self.garbage_collector = SmartGarbageCollector()
        self.cache = MemoryCache()
        self.object_pools: Dict[str, ObjectPool] = {}

        # 注册内存监控回调
        self.monitor.add_callback(self._on_memory_change)

        self.logger = logging.getLogger(__name__)

    def _on_memory_change(self, stats: MemoryStats):
        """内存状态变化处理"""
        # 自动垃圾收集
        self.garbage_collector.check_and_collect(stats.memory_percent)

        # 在内存紧张时清理缓存
        if stats.memory_percent > 90:
            self.logger.warning("内存紧张，清理缓存")
            self.cache.clear()

    async def start(self):
        """启动内存管理"""
        await self.monitor.start_monitoring()
        self.logger.info("内存管理器已启动")

    async def stop(self):
        """停止内存管理"""
        await self.monitor.stop_monitoring()
        self.logger.info("内存管理器已停止")

    def create_object_pool(self, name: str, factory_func: Callable, max_size: int = 100):
        """创建对象池"""
        self.object_pools[name] = ObjectPool(factory_func, max_size)
        return self.object_pools[name]

    def get_object_pool(self, name: str) -> Optional[ObjectPool]:
        """获取对象池"""
        return self.object_pools.get(name)

    def get_comprehensive_stats(self) -> Dict:
        """获取综合统计信息"""
        memory_stats = self.monitor.get_memory_stats()
        memory_trend = self.monitor.get_memory_trend()
        cache_stats = self.cache.get_stats()
        gc_stats = self.garbage_collector.get_gc_stats()

        pool_stats = {}
        for name, pool in self.object_pools.items():
            pool_stats[name] = pool.get_stats()

        return {
            "memory": {
                "current": memory_stats,
                "trend": memory_trend
            },
            "cache": cache_stats,
            "garbage_collection": gc_stats,
            "object_pools": pool_stats
        }

    def optimize_memory(self):
        """手动优化内存"""
        self.logger.info("开始手动内存优化...")

        # 清理缓存
        self.cache.clear()

        # 强制GC
        self.garbage_collector._force_gc()

        # 重置对象池
        for pool in self.object_pools.values():
            pool.pool.clear()

        self.logger.info("手动内存优化完成")


# 全局内存管理器实例
_memory_manager = None


def get_memory_manager() -> MemoryManager:
    """获取全局内存管理器"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


# 使用示例和装饰器
def memory_optimized(func):
    """内存优化装饰器"""
    def wrapper(*args, **kwargs):
        manager = get_memory_manager()

        # 执行前检查内存
        before_stats = manager.monitor.get_memory_stats()

        try:
            result = func(*args, **kwargs)
            return result
        finally:
            # 执行后检查内存
            after_stats = manager.monitor.get_memory_stats()
            memory_increase = after_stats.process_memory - before_stats.process_memory

            if memory_increase > 10 * 1024 * 1024:  # 增长超过10MB
                manager.logger.warning(f"函数 {func.__name__} 导致内存增长 {memory_increase/1024/1024:.1f}MB")
                # 可选择性执行GC
                manager.garbage_collector._auto_gc()

    return wrapper


if __name__ == "__main__":
    # 测试内存管理器
    async def test_memory_manager():
        manager = get_memory_manager()
        await manager.start()

        # 创建对象池
        def create_buffer():
            return bytearray(1024)

        buffer_pool = manager.create_object_pool("buffers", create_buffer, 50)

        # 测试对象池
        buffer1 = buffer_pool.acquire()
        buffer2 = buffer_pool.acquire()
        buffer_pool.release(buffer1)
        buffer_pool.release(buffer2)

        # 测试缓存
        manager.cache.set("test_key", "test_value")
        value = manager.cache.get("test_key")
        print(f"缓存测试: {value}")

        # 获取统计信息
        stats = manager.get_comprehensive_stats()
        print(f"内存统计: {stats}")

        await asyncio.sleep(10)  # 监控10秒
        await manager.stop()

    asyncio.run(test_memory_manager())