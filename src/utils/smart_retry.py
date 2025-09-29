"""
智能重试机制 - 根据错误类型和网络状况智能调整重试策略
"""

import asyncio
import time
import random
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import statistics
from collections import deque
import aiohttp


class RetryReason(Enum):
    """重试原因"""
    NETWORK_TIMEOUT = "network_timeout"
    CONNECTION_ERROR = "connection_error"
    HTTP_ERROR = "http_error"
    SERVER_ERROR = "server_error"
    RATE_LIMITED = "rate_limited"
    TEMPORARY_FAILURE = "temporary_failure"
    PARSING_ERROR = "parsing_error"
    UNKNOWN = "unknown"


@dataclass
class RetryAttempt:
    """重试尝试记录"""
    attempt_number: int
    timestamp: float
    delay_before: float
    reason: RetryReason
    error_message: str
    success: bool = False
    response_time: Optional[float] = None


@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter_factor: float = 0.1
    timeout_multiplier: float = 1.5
    success_reset_threshold: int = 3  # 连续成功次数后重置失败计数


class NetworkConditionMonitor:
    """网络状况监控器"""

    def __init__(self, history_size: int = 100):
        self.response_times = deque(maxlen=history_size)
        self.error_rates = deque(maxlen=history_size)
        self.success_rates = deque(maxlen=history_size)
        self.bandwidth_samples = deque(maxlen=history_size)

        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.last_update = time.time()

    def record_attempt(self, success: bool, response_time: Optional[float] = None, bytes_transferred: int = 0):
        """记录尝试结果"""
        current_time = time.time()

        if success:
            self.consecutive_successes += 1
            self.consecutive_failures = 0

            if response_time is not None:
                self.response_times.append(response_time)

                # 计算带宽（简化计算）
                if bytes_transferred > 0:
                    bandwidth = bytes_transferred / response_time / 1024  # KB/s
                    self.bandwidth_samples.append(bandwidth)
        else:
            self.consecutive_failures += 1
            self.consecutive_successes = 0

        # 更新错误率和成功率
        total_attempts = len(self.error_rates) + 1
        error_count = sum(1 for rate in self.error_rates if rate > 0) + (0 if success else 1)

        error_rate = error_count / total_attempts
        success_rate = 1.0 - error_rate

        self.error_rates.append(error_rate)
        self.success_rates.append(success_rate)
        self.last_update = current_time

    def get_network_condition(self) -> Dict[str, Any]:
        """获取当前网络状况"""
        condition = {
            'quality': 'unknown',
            'avg_response_time': None,
            'error_rate': 0.0,
            'success_rate': 1.0,
            'avg_bandwidth': None,
            'consecutive_failures': self.consecutive_failures,
            'consecutive_successes': self.consecutive_successes
        }

        if self.response_times:
            condition['avg_response_time'] = statistics.mean(self.response_times)

        if self.error_rates:
            condition['error_rate'] = self.error_rates[-1] if self.error_rates else 0.0

        if self.success_rates:
            condition['success_rate'] = self.success_rates[-1] if self.success_rates else 1.0

        if self.bandwidth_samples:
            condition['avg_bandwidth'] = statistics.mean(self.bandwidth_samples)

        # 评估网络质量
        if condition['error_rate'] > 0.3:
            condition['quality'] = 'poor'
        elif condition['error_rate'] > 0.1:
            condition['quality'] = 'fair'
        elif condition['avg_response_time'] and condition['avg_response_time'] > 5.0:
            condition['quality'] = 'slow'
        else:
            condition['quality'] = 'good'

        return condition

    def should_use_conservative_strategy(self) -> bool:
        """是否应该使用保守策略"""
        condition = self.get_network_condition()
        return (
            condition['quality'] in ['poor', 'fair'] or
            self.consecutive_failures >= 3 or
            condition['error_rate'] > 0.2
        )


class SmartRetryStrategy:
    """智能重试策略"""

    def __init__(self, config: RetryConfig = None):
        self.config = config or RetryConfig()
        self.network_monitor = NetworkConditionMonitor()
        self.retry_history: Dict[str, List[RetryAttempt]] = {}
        self.logger = logging.getLogger(__name__)

    def classify_error(self, exception: Exception) -> RetryReason:
        """分类错误以确定重试原因"""
        error_str = str(exception).lower()
        error_type = type(exception).__name__.lower()

        # 网络超时
        if 'timeout' in error_str or 'timeout' in error_type:
            return RetryReason.NETWORK_TIMEOUT

        # 连接错误
        if any(keyword in error_str for keyword in ['connection', 'connect', 'unreachable']):
            return RetryReason.CONNECTION_ERROR

        # HTTP错误
        if isinstance(exception, aiohttp.ClientResponseError):
            if exception.status == 429:
                return RetryReason.RATE_LIMITED
            elif 500 <= exception.status < 600:
                return RetryReason.SERVER_ERROR
            else:
                return RetryReason.HTTP_ERROR

        # 临时失败
        if any(keyword in error_str for keyword in ['temporary', 'busy', 'unavailable']):
            return RetryReason.TEMPORARY_FAILURE

        # 解析错误
        if any(keyword in error_str for keyword in ['parse', 'decode', 'invalid']):
            return RetryReason.PARSING_ERROR

        return RetryReason.UNKNOWN

    def calculate_delay(self, attempt: int, reason: RetryReason, network_condition: Dict[str, Any]) -> float:
        """计算重试延迟"""
        base_delay = self.config.base_delay

        # 根据错误类型调整基础延迟
        reason_multipliers = {
            RetryReason.RATE_LIMITED: 5.0,
            RetryReason.SERVER_ERROR: 3.0,
            RetryReason.NETWORK_TIMEOUT: 2.0,
            RetryReason.CONNECTION_ERROR: 1.5,
            RetryReason.HTTP_ERROR: 1.0,
            RetryReason.TEMPORARY_FAILURE: 2.0,
            RetryReason.PARSING_ERROR: 0.5,
            RetryReason.UNKNOWN: 1.0
        }

        base_delay *= reason_multipliers.get(reason, 1.0)

        # 根据网络状况调整
        if network_condition['quality'] == 'poor':
            base_delay *= 2.0
        elif network_condition['quality'] == 'fair':
            base_delay *= 1.5

        # 指数退避
        exponential_delay = base_delay * (self.config.exponential_base ** (attempt - 1))

        # 应用抖动以避免雷群效应
        jitter = random.uniform(-self.config.jitter_factor, self.config.jitter_factor)
        jittered_delay = exponential_delay * (1 + jitter)

        # 限制最大延迟
        final_delay = min(jittered_delay, self.config.max_delay)

        return max(0.1, final_delay)  # 最小延迟0.1秒

    def should_retry(self, attempt: int, reason: RetryReason, operation_id: str) -> bool:
        """判断是否应该重试"""
        if attempt >= self.config.max_attempts:
            return False

        # 某些错误类型不应该重试
        no_retry_reasons = {RetryReason.PARSING_ERROR}
        if reason in no_retry_reasons:
            return False

        # 检查历史成功率
        if operation_id in self.retry_history:
            history = self.retry_history[operation_id]
            if len(history) >= 5:  # 至少5次尝试才评估
                success_rate = sum(1 for h in history[-10:] if h.success) / min(10, len(history))
                if success_rate < 0.1:  # 成功率低于10%，停止重试
                    self.logger.warning(f"操作 {operation_id} 成功率过低 ({success_rate:.1%})，停止重试")
                    return False

        return True

    async def execute_with_retry(self,
                                operation: Callable,
                                operation_id: str,
                                *args,
                                **kwargs) -> Any:
        """执行带重试的操作"""
        if operation_id not in self.retry_history:
            self.retry_history[operation_id] = []

        attempt = 1
        last_exception = None

        while True:
            start_time = time.time()

            try:
                # 记录尝试开始
                self.logger.debug(f"尝试执行操作 {operation_id}，第 {attempt} 次")

                # 执行操作
                result = await operation(*args, **kwargs)

                # 记录成功
                response_time = time.time() - start_time
                self.network_monitor.record_attempt(True, response_time)

                attempt_record = RetryAttempt(
                    attempt_number=attempt,
                    timestamp=start_time,
                    delay_before=0.0,
                    reason=RetryReason.UNKNOWN,
                    error_message="",
                    success=True,
                    response_time=response_time
                )
                self.retry_history[operation_id].append(attempt_record)

                self.logger.info(f"操作 {operation_id} 执行成功，耗时 {response_time:.2f}s")
                return result

            except Exception as e:
                last_exception = e
                response_time = time.time() - start_time

                # 分类错误
                reason = self.classify_error(e)

                # 记录失败
                self.network_monitor.record_attempt(False, response_time)

                # 判断是否应该重试
                if not self.should_retry(attempt, reason, operation_id):
                    self.logger.error(f"操作 {operation_id} 最终失败，不再重试: {e}")
                    break

                # 计算延迟
                network_condition = self.network_monitor.get_network_condition()
                delay = self.calculate_delay(attempt, reason, network_condition)

                # 记录重试尝试
                attempt_record = RetryAttempt(
                    attempt_number=attempt,
                    timestamp=start_time,
                    delay_before=delay,
                    reason=reason,
                    error_message=str(e),
                    success=False,
                    response_time=response_time
                )
                self.retry_history[operation_id].append(attempt_record)

                self.logger.warning(
                    f"操作 {operation_id} 第 {attempt} 次尝试失败: {e}, "
                    f"原因: {reason.value}, 延迟 {delay:.2f}s 后重试"
                )

                # 等待后重试
                await asyncio.sleep(delay)
                attempt += 1

        # 所有重试都失败了
        raise last_exception

    def get_retry_statistics(self, operation_id: str = None) -> Dict[str, Any]:
        """获取重试统计信息"""
        if operation_id:
            # 特定操作的统计
            if operation_id not in self.retry_history:
                return {}

            history = self.retry_history[operation_id]
            total_attempts = len(history)
            successful_attempts = sum(1 for h in history if h.success)

            if total_attempts == 0:
                return {}

            return {
                'operation_id': operation_id,
                'total_attempts': total_attempts,
                'successful_attempts': successful_attempts,
                'success_rate': successful_attempts / total_attempts,
                'avg_response_time': statistics.mean([h.response_time for h in history if h.response_time]),
                'most_common_reason': self._get_most_common_reason(history)
            }
        else:
            # 全局统计
            all_attempts = []
            for history in self.retry_history.values():
                all_attempts.extend(history)

            if not all_attempts:
                return {}

            total_attempts = len(all_attempts)
            successful_attempts = sum(1 for a in all_attempts if a.success)

            # 按原因分组统计
            reason_stats = {}
            for attempt in all_attempts:
                reason = attempt.reason.value
                if reason not in reason_stats:
                    reason_stats[reason] = {'count': 0, 'success_count': 0}
                reason_stats[reason]['count'] += 1
                if attempt.success:
                    reason_stats[reason]['success_count'] += 1

            # 计算每个原因的成功率
            for reason_data in reason_stats.values():
                reason_data['success_rate'] = reason_data['success_count'] / reason_data['count']

            return {
                'total_operations': len(self.retry_history),
                'total_attempts': total_attempts,
                'successful_attempts': successful_attempts,
                'overall_success_rate': successful_attempts / total_attempts,
                'network_condition': self.network_monitor.get_network_condition(),
                'reason_statistics': reason_stats
            }

    def _get_most_common_reason(self, history: List[RetryAttempt]) -> str:
        """获取最常见的失败原因"""
        failed_attempts = [h for h in history if not h.success]
        if not failed_attempts:
            return "none"

        reason_counts = {}
        for attempt in failed_attempts:
            reason = attempt.reason.value
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

        return max(reason_counts.items(), key=lambda x: x[1])[0]

    def reset_history(self, operation_id: str = None):
        """重置重试历史"""
        if operation_id:
            if operation_id in self.retry_history:
                del self.retry_history[operation_id]
        else:
            self.retry_history.clear()
            # 重置网络监控器
            self.network_monitor = NetworkConditionMonitor()

    def adjust_config_based_on_performance(self):
        """根据性能自动调整配置"""
        stats = self.get_retry_statistics()
        if not stats:
            return

        overall_success_rate = stats.get('overall_success_rate', 1.0)
        network_condition = self.network_monitor.get_network_condition()

        # 如果成功率很低，增加重试次数和延迟
        if overall_success_rate < 0.5:
            self.config.max_attempts = min(10, self.config.max_attempts + 1)
            self.config.base_delay = min(5.0, self.config.base_delay * 1.2)
            self.logger.info("检测到低成功率，增加重试次数和延迟")

        # 如果网络状况很好，可以减少延迟
        elif network_condition['quality'] == 'good' and overall_success_rate > 0.9:
            self.config.base_delay = max(0.5, self.config.base_delay * 0.9)
            self.logger.info("检测到良好网络状况，减少重试延迟")


# 全局重试策略实例
_retry_strategy = None


def get_retry_strategy() -> SmartRetryStrategy:
    """获取全局重试策略"""
    global _retry_strategy
    if _retry_strategy is None:
        _retry_strategy = SmartRetryStrategy()
    return _retry_strategy


# 装饰器
def smart_retry(operation_id: str = None,
               max_attempts: int = None,
               base_delay: float = None):
    """智能重试装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            retry_strategy = get_retry_strategy()

            # 临时调整配置
            original_config = None
            if max_attempts is not None or base_delay is not None:
                original_config = (retry_strategy.config.max_attempts, retry_strategy.config.base_delay)
                if max_attempts is not None:
                    retry_strategy.config.max_attempts = max_attempts
                if base_delay is not None:
                    retry_strategy.config.base_delay = base_delay

            try:
                op_id = operation_id or f"{func.__name__}_{id(func)}"
                result = await retry_strategy.execute_with_retry(func, op_id, *args, **kwargs)
                return result
            finally:
                # 恢复原始配置
                if original_config:
                    retry_strategy.config.max_attempts, retry_strategy.config.base_delay = original_config

        return wrapper
    return decorator


# 使用示例
@smart_retry(operation_id="download_segment", max_attempts=3)
async def download_segment(url: str) -> bytes:
    """示例：下载片段"""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.read()


if __name__ == "__main__":
    # 测试智能重试
    async def test_smart_retry():
        retry_strategy = get_retry_strategy()

        # 模拟一个经常失败的操作
        async def flaky_operation(success_rate: float = 0.3):
            if random.random() < success_rate:
                return "success"
            else:
                raise aiohttp.ClientError("随机失败")

        # 执行多次测试
        results = []
        for i in range(10):
            try:
                result = await retry_strategy.execute_with_retry(
                    flaky_operation, f"test_operation_{i}", 0.3
                )
                results.append(True)
            except:
                results.append(False)

        # 获取统计信息
        for i in range(10):
            stats = retry_strategy.get_retry_statistics(f"test_operation_{i}")
            print(f"操作 {i} 统计: {json.dumps(stats, indent=2, ensure_ascii=False)}")

        global_stats = retry_strategy.get_retry_statistics()
        print(f"全局统计: {json.dumps(global_stats, indent=2, ensure_ascii=False)}")

        success_count = sum(results)
        print(f"总体成功率: {success_count}/10 = {success_count/10:.1%}")

    asyncio.run(test_smart_retry())