"""
增强的错误处理系统 - 提供全面的异常处理和恢复机制
"""

import traceback
import functools
import asyncio
import time
import logging
from typing import Dict, List, Optional, Callable, Any, Type, Union
from dataclasses import dataclass
from enum import Enum
import json
import sys
from pathlib import Path


class ErrorSeverity(Enum):
    """错误严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """错误分类"""
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    PARSING = "parsing"
    MEMORY = "memory"
    SYSTEM = "system"
    USER_INPUT = "user_input"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


@dataclass
class ErrorInfo:
    """错误信息"""
    error_id: str
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    original_exception: Optional[Exception]
    traceback_str: str
    timestamp: float
    context: Dict[str, Any]
    retry_count: int = 0
    max_retries: int = 3
    last_retry_time: Optional[float] = None


class ErrorClassifier:
    """错误分类器"""

    def __init__(self):
        self.network_keywords = [
            'timeout', 'connection', 'dns', 'socket', 'http', 'ssl',
            'certificate', 'proxy', 'host', 'network', 'unreachable'
        ]

        self.filesystem_keywords = [
            'permission', 'file', 'directory', 'disk', 'space',
            'path', 'exists', 'write', 'read', 'access'
        ]

        self.memory_keywords = [
            'memory', 'allocation', 'out of memory', 'malloc',
            'heap', 'stack overflow', 'segmentation'
        ]

    def classify_error(self, exception: Exception, context: Dict[str, Any] = None) -> ErrorCategory:
        """分类错误"""
        error_str = str(exception).lower()
        error_type = type(exception).__name__.lower()

        # 根据异常类型直接分类
        if any(t in error_type for t in ['http', 'ssl', 'socket', 'timeout', 'connection']):
            return ErrorCategory.NETWORK

        if any(t in error_type for t in ['file', 'permission', 'os']):
            return ErrorCategory.FILESYSTEM

        if any(t in error_type for t in ['memory', 'allocation']):
            return ErrorCategory.MEMORY

        if any(t in error_type for t in ['value', 'type', 'attribute']):
            return ErrorCategory.USER_INPUT

        if any(t in error_type for t in ['parse', 'json', 'decode']):
            return ErrorCategory.PARSING

        # 根据错误消息分类
        if any(keyword in error_str for keyword in self.network_keywords):
            return ErrorCategory.NETWORK

        if any(keyword in error_str for keyword in self.filesystem_keywords):
            return ErrorCategory.FILESYSTEM

        if any(keyword in error_str for keyword in self.memory_keywords):
            return ErrorCategory.MEMORY

        return ErrorCategory.UNKNOWN

    def determine_severity(self, exception: Exception, category: ErrorCategory) -> ErrorSeverity:
        """确定错误严重程度"""
        error_str = str(exception).lower()

        # 根据异常类型确定严重程度
        critical_exceptions = [
            'systemexit', 'keyboardinterrupt', 'memoryerror',
            'recursionerror', 'syntaxerror'
        ]

        high_exceptions = [
            'filenotfounderror', 'permissionerror', 'connectionerror',
            'timeouterror', 'oserror'
        ]

        medium_exceptions = [
            'httperror', 'valueerror', 'typeerror', 'attributeerror'
        ]

        exception_name = type(exception).__name__.lower()

        if any(exc in exception_name for exc in critical_exceptions):
            return ErrorSeverity.CRITICAL

        if any(exc in exception_name for exc in high_exceptions):
            return ErrorSeverity.HIGH

        if any(exc in exception_name for exc in medium_exceptions):
            return ErrorSeverity.MEDIUM

        # 根据错误内容判断
        if any(keyword in error_str for keyword in ['critical', 'fatal', 'corruption']):
            return ErrorSeverity.CRITICAL

        if any(keyword in error_str for keyword in ['failed', 'error', 'exception']):
            return ErrorSeverity.HIGH

        return ErrorSeverity.LOW


class ErrorRecoveryStrategy:
    """错误恢复策略"""

    def __init__(self):
        self.strategies: Dict[ErrorCategory, List[Callable]] = {
            ErrorCategory.NETWORK: [
                self._retry_with_backoff,
                self._switch_to_backup_url,
                self._reduce_concurrent_connections,
                self._check_network_connectivity
            ],
            ErrorCategory.FILESYSTEM: [
                self._check_disk_space,
                self._create_missing_directories,
                self._change_output_location,
                self._cleanup_temp_files
            ],
            ErrorCategory.MEMORY: [
                self._free_memory,
                self._reduce_concurrent_tasks,
                self._enable_streaming_mode,
                self._restart_with_lower_settings
            ],
            ErrorCategory.PARSING: [
                self._retry_with_different_parser,
                self._validate_input_format,
                self._use_fallback_parsing
            ]
        }

    async def recover(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """尝试错误恢复"""
        strategies = self.strategies.get(error_info.category, [])

        for strategy in strategies:
            try:
                success = await strategy(error_info, context)
                if success:
                    return True
            except Exception as e:
                logging.warning(f"恢复策略失败: {strategy.__name__}: {e}")

        return False

    async def _retry_with_backoff(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """带退避的重试"""
        if error_info.retry_count >= error_info.max_retries:
            return False

        delay = min(2 ** error_info.retry_count, 60)  # 最大60秒
        await asyncio.sleep(delay)

        error_info.retry_count += 1
        error_info.last_retry_time = time.time()
        return True

    async def _switch_to_backup_url(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """切换到备用URL"""
        backup_urls = context.get('backup_urls', [])
        if backup_urls:
            context['current_url'] = backup_urls.pop(0)
            return True
        return False

    async def _reduce_concurrent_connections(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """减少并发连接数"""
        current_concurrent = context.get('concurrent_connections', 8)
        if current_concurrent > 2:
            new_concurrent = max(2, current_concurrent // 2)
            context['concurrent_connections'] = new_concurrent
            return True
        return False

    async def _check_network_connectivity(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """检查网络连接"""
        try:
            import subprocess
            result = subprocess.run(['ping', '-c', '1', 'google.com'],
                                  capture_output=True, timeout=5)
            return result.returncode == 0
        except:
            return False

    async def _check_disk_space(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """检查磁盘空间"""
        output_path = context.get('output_path', '.')
        try:
            import shutil
            free_space = shutil.disk_usage(output_path).free
            required_space = context.get('estimated_size', 1024 * 1024 * 100)  # 默认100MB
            return free_space > required_space
        except:
            return False

    async def _create_missing_directories(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """创建缺失的目录"""
        output_path = context.get('output_path')
        if output_path:
            try:
                Path(output_path).mkdir(parents=True, exist_ok=True)
                return True
            except:
                pass
        return False

    async def _change_output_location(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """更改输出位置"""
        alternative_paths = [
            Path.home() / 'Downloads',
            Path('/tmp'),
            Path('.')
        ]

        for path in alternative_paths:
            try:
                if path.exists() and path.is_dir():
                    context['output_path'] = str(path)
                    return True
            except:
                continue
        return False

    async def _cleanup_temp_files(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """清理临时文件"""
        temp_path = context.get('temp_path')
        if temp_path:
            try:
                import shutil
                if Path(temp_path).exists():
                    shutil.rmtree(temp_path)
                return True
            except:
                pass
        return False

    async def _free_memory(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """释放内存"""
        try:
            import gc
            gc.collect()

            # 可以添加更多内存释放逻辑
            from ..utils.memory_manager import get_memory_manager
            memory_manager = get_memory_manager()
            memory_manager.optimize_memory()

            return True
        except:
            return False

    async def _reduce_concurrent_tasks(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """减少并发任务数"""
        current_tasks = context.get('concurrent_tasks', 8)
        if current_tasks > 2:
            context['concurrent_tasks'] = max(2, current_tasks // 2)
            return True
        return False

    async def _enable_streaming_mode(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """启用流式模式"""
        context['streaming_mode'] = True
        context['chunk_size'] = min(context.get('chunk_size', 8192), 4096)
        return True

    async def _restart_with_lower_settings(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """使用较低设置重启"""
        context['low_memory_mode'] = True
        context['concurrent_connections'] = 2
        context['chunk_size'] = 4096
        return True

    async def _retry_with_different_parser(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """使用不同的解析器重试"""
        current_parser = context.get('parser_type', 'default')
        alternative_parsers = ['strict', 'lenient', 'regex']

        if current_parser in alternative_parsers:
            alternative_parsers.remove(current_parser)

        if alternative_parsers:
            context['parser_type'] = alternative_parsers[0]
            return True
        return False

    async def _validate_input_format(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """验证输入格式"""
        input_data = context.get('input_data')
        if input_data:
            # 添加格式验证逻辑
            return True
        return False

    async def _use_fallback_parsing(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """使用回退解析"""
        context['use_fallback_parser'] = True
        return True


class ErrorReporter:
    """错误报告器"""

    def __init__(self, report_file: Optional[str] = None):
        self.report_file = report_file or str(Path.home() / '.m3u8_downloader' / 'error_reports.json')
        self.reports: List[Dict] = []
        self.logger = logging.getLogger(__name__)

    def report_error(self, error_info: ErrorInfo, context: Dict[str, Any] = None):
        """报告错误"""
        report = {
            'error_id': error_info.error_id,
            'category': error_info.category.value,
            'severity': error_info.severity.value,
            'message': error_info.message,
            'timestamp': error_info.timestamp,
            'traceback': error_info.traceback_str,
            'context': context or {},
            'retry_count': error_info.retry_count,
            'system_info': self._get_system_info()
        }

        self.reports.append(report)
        self._save_report(report)

        # 根据严重程度记录日志
        if error_info.severity == ErrorSeverity.CRITICAL:
            self.logger.critical(f"CRITICAL ERROR: {error_info.message}")
        elif error_info.severity == ErrorSeverity.HIGH:
            self.logger.error(f"HIGH SEVERITY: {error_info.message}")
        elif error_info.severity == ErrorSeverity.MEDIUM:
            self.logger.warning(f"MEDIUM SEVERITY: {error_info.message}")
        else:
            self.logger.info(f"LOW SEVERITY: {error_info.message}")

    def _get_system_info(self) -> Dict[str, Any]:
        """获取系统信息"""
        try:
            import platform
            import psutil

            return {
                'platform': platform.platform(),
                'python_version': platform.python_version(),
                'memory_usage': psutil.virtual_memory().percent,
                'cpu_count': psutil.cpu_count(),
                'disk_usage': psutil.disk_usage('/').percent if platform.system() != 'Windows' else psutil.disk_usage('C:').percent
            }
        except:
            return {}

    def _save_report(self, report: Dict):
        """保存错误报告"""
        try:
            Path(self.report_file).parent.mkdir(parents=True, exist_ok=True)

            # 读取现有报告
            existing_reports = []
            if Path(self.report_file).exists():
                with open(self.report_file, 'r', encoding='utf-8') as f:
                    existing_reports = json.load(f)

            # 添加新报告
            existing_reports.append(report)

            # 保持最近1000个报告
            if len(existing_reports) > 1000:
                existing_reports = existing_reports[-1000:]

            # 保存
            with open(self.report_file, 'w', encoding='utf-8') as f:
                json.dump(existing_reports, f, indent=2, ensure_ascii=False)

        except Exception as e:
            self.logger.error(f"保存错误报告失败: {e}")

    def get_error_statistics(self) -> Dict[str, Any]:
        """获取错误统计信息"""
        if not self.reports:
            return {}

        # 按分类统计
        category_stats = {}
        severity_stats = {}

        for report in self.reports:
            category = report['category']
            severity = report['severity']

            category_stats[category] = category_stats.get(category, 0) + 1
            severity_stats[severity] = severity_stats.get(severity, 0) + 1

        return {
            'total_errors': len(self.reports),
            'by_category': category_stats,
            'by_severity': severity_stats,
            'most_common_category': max(category_stats.items(), key=lambda x: x[1]) if category_stats else None,
            'most_common_severity': max(severity_stats.items(), key=lambda x: x[1]) if severity_stats else None
        }


class EnhancedErrorHandler:
    """增强的错误处理器"""

    def __init__(self):
        self.classifier = ErrorClassifier()
        self.recovery_strategy = ErrorRecoveryStrategy()
        self.reporter = ErrorReporter()
        self.error_history: Dict[str, ErrorInfo] = {}
        self.logger = logging.getLogger(__name__)

    async def handle_error(self,
                          exception: Exception,
                          context: Dict[str, Any] = None,
                          operation_id: str = None) -> bool:
        """处理错误"""
        context = context or {}
        error_id = operation_id or str(id(exception))

        # 分类错误
        category = self.classifier.classify_error(exception, context)
        severity = self.classifier.determine_severity(exception, category)

        # 创建错误信息
        error_info = ErrorInfo(
            error_id=error_id,
            category=category,
            severity=severity,
            message=str(exception),
            original_exception=exception,
            traceback_str=traceback.format_exc(),
            timestamp=time.time(),
            context=context.copy()
        )

        # 检查是否是重复错误
        if error_id in self.error_history:
            prev_error = self.error_history[error_id]
            error_info.retry_count = prev_error.retry_count
            error_info.last_retry_time = prev_error.last_retry_time

        # 报告错误
        self.reporter.report_error(error_info, context)

        # 尝试恢复
        recovery_success = False
        if severity != ErrorSeverity.CRITICAL:
            try:
                recovery_success = await self.recovery_strategy.recover(error_info, context)
                if recovery_success:
                    self.logger.info(f"错误恢复成功: {error_id}")
                else:
                    self.logger.warning(f"错误恢复失败: {error_id}")
            except Exception as recovery_error:
                self.logger.error(f"错误恢复过程中发生异常: {recovery_error}")

        # 更新错误历史
        self.error_history[error_id] = error_info

        return recovery_success

    def get_error_summary(self) -> Dict[str, Any]:
        """获取错误摘要"""
        stats = self.reporter.get_error_statistics()
        recent_errors = [
            {
                'id': info.error_id,
                'category': info.category.value,
                'severity': info.severity.value,
                'message': info.message,
                'timestamp': info.timestamp
            }
            for info in list(self.error_history.values())[-10:]  # 最近10个错误
        ]

        return {
            'statistics': stats,
            'recent_errors': recent_errors,
            'total_handled': len(self.error_history)
        }


# 全局错误处理器实例
_error_handler = None


def get_error_handler() -> EnhancedErrorHandler:
    """获取全局错误处理器"""
    global _error_handler
    if _error_handler is None:
        _error_handler = EnhancedErrorHandler()
    return _error_handler


# 装饰器
def error_handler(operation_id: str = None,
                 context: Dict[str, Any] = None,
                 reraise: bool = False):
    """错误处理装饰器"""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            handler = get_error_handler()
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                op_id = operation_id or f"{func.__name__}_{id(func)}"
                recovery_success = await handler.handle_error(e, context, op_id)

                if reraise or not recovery_success:
                    raise
                return None

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            handler = get_error_handler()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                op_id = operation_id or f"{func.__name__}_{id(func)}"
                # 对于同步函数，只记录错误，不尝试恢复
                asyncio.create_task(handler.handle_error(e, context, op_id))

                if reraise:
                    raise
                return None

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def safe_execute(func: Callable, *args, **kwargs) -> Any:
    """安全执行函数"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        handler = get_error_handler()
        asyncio.create_task(handler.handle_error(e, {'function': func.__name__}))
        return None


# 使用示例
@error_handler(operation_id="download_segment", reraise=False)
async def download_segment_with_error_handling(url: str, output_path: str):
    """带错误处理的片段下载示例"""
    # 下载逻辑
    pass


if __name__ == "__main__":
    # 测试错误处理
    async def test_error_handling():
        handler = get_error_handler()

        # 模拟不同类型的错误
        test_errors = [
            ConnectionError("网络连接失败"),
            FileNotFoundError("文件未找到"),
            MemoryError("内存不足"),
            ValueError("无效的参数值")
        ]

        for error in test_errors:
            context = {'test': True, 'operation': 'test_download'}
            await handler.handle_error(error, context)

        # 获取错误摘要
        summary = handler.get_error_summary()
        print(f"错误处理摘要: {json.dumps(summary, indent=2, ensure_ascii=False)}")

    asyncio.run(test_error_handling())