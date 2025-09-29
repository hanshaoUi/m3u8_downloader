import logging
import logging.handlers
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import json


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器（用于控制台输出）"""

    # ANSI颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
        'RESET': '\033[0m'        # 重置
    }

    def format(self, record):
        # 添加颜色
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"

        return super().format(record)


class JsonFormatter(logging.Formatter):
    """JSON格式的日志格式化器"""

    def format(self, record):
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }

        # 添加额外的字段
        if hasattr(record, 'extra_data'):
            log_entry['extra'] = record.extra_data

        # 添加异常信息
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


class LogManager:
    """日志管理器"""

    def __init__(self,
                 app_name: str = "M3U8Downloader",
                 log_dir: Optional[str] = None,
                 max_file_size: int = 10 * 1024 * 1024,  # 10MB
                 backup_count: int = 5,
                 console_level: str = "INFO",
                 file_level: str = "DEBUG"):
        """
        初始化日志管理器

        Args:
            app_name: 应用名称
            log_dir: 日志目录，如果为None则使用默认位置
            max_file_size: 单个日志文件最大大小（字节）
            backup_count: 保留的日志文件数量
            console_level: 控制台日志级别
            file_level: 文件日志级别
        """
        self.app_name = app_name
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self.console_level = console_level.upper()
        self.file_level = file_level.upper()

        # 设置日志目录
        if log_dir is None:
            self.log_dir = Path.home() / ".m3u8_downloader" / "logs"
        else:
            self.log_dir = Path(log_dir)

        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 日志文件路径
        self.log_files = {
            'app': self.log_dir / f"{app_name.lower()}.log",
            'error': self.log_dir / f"{app_name.lower()}_error.log",
            'json': self.log_dir / f"{app_name.lower()}.json.log"
        }

        # 已配置的logger列表
        self._configured_loggers = set()

        # 设置根logger
        self.setup_root_logger()

    def setup_root_logger(self):
        """设置根logger"""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        # 清除已有的处理器
        root_logger.handlers.clear()

        # 添加控制台处理器
        self.add_console_handler(root_logger)

        # 添加文件处理器
        self.add_file_handlers(root_logger)

    def add_console_handler(self, logger):
        """添加控制台处理器"""
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, self.console_level))

        # 使用带颜色的格式化器
        colored_formatter = ColoredFormatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(colored_formatter)

        logger.addHandler(console_handler)

    def add_file_handlers(self, logger):
        """添加文件处理器"""
        # 主日志文件处理器
        main_handler = logging.handlers.RotatingFileHandler(
            self.log_files['app'],
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        main_handler.setLevel(getattr(logging, self.file_level))

        main_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        main_handler.setFormatter(main_formatter)

        logger.addHandler(main_handler)

        # 错误日志文件处理器
        error_handler = logging.handlers.RotatingFileHandler(
            self.log_files['error'],
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(main_formatter)

        logger.addHandler(error_handler)

        # JSON格式日志处理器
        json_handler = logging.handlers.RotatingFileHandler(
            self.log_files['json'],
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8'
        )
        json_handler.setLevel(getattr(logging, self.file_level))

        json_formatter = JsonFormatter()
        json_handler.setFormatter(json_formatter)

        logger.addHandler(json_handler)

    def get_logger(self, name: str) -> logging.Logger:
        """获取指定名称的logger"""
        logger = logging.getLogger(name)

        # 如果这个logger还没有配置过，则进行配置
        if name not in self._configured_loggers:
            logger.setLevel(logging.DEBUG)
            # 防止日志传播到父logger（避免重复输出）
            logger.propagate = True
            self._configured_loggers.add(name)

        return logger

    def set_level(self, level: str, handler_type: str = "all"):
        """
        设置日志级别

        Args:
            level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            handler_type: 处理器类型 (console, file, all)
        """
        level = level.upper()
        log_level = getattr(logging, level)

        root_logger = logging.getLogger()

        for handler in root_logger.handlers:
            if handler_type == "all":
                handler.setLevel(log_level)
            elif handler_type == "console" and isinstance(handler, logging.StreamHandler):
                handler.setLevel(log_level)
            elif handler_type == "file" and isinstance(handler, logging.handlers.RotatingFileHandler):
                handler.setLevel(log_level)

    def log_system_info(self):
        """记录系统信息"""
        logger = self.get_logger("system")

        try:
            import platform
            import psutil

            # Windows系统使用C:盘，Unix系统使用根目录
            disk_path = 'C:\\' if platform.system() == 'Windows' else '/'

            disk_info = psutil.disk_usage(disk_path)

            system_info = {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "cpu_count": psutil.cpu_count(),
                "memory_total": psutil.virtual_memory().total,
                "disk_usage": {
                    "total": disk_info.total,
                    "used": disk_info.used,
                    "free": disk_info.free
                },
            }

            logger.info("系统信息", extra={'extra_data': system_info})

        except Exception as e:
            logger.warning(f"获取系统信息失败: {e}")

    def log_app_start(self):
        """记录应用启动"""
        logger = self.get_logger("app")
        logger.info(f"{self.app_name} 应用启动")

    def log_app_stop(self):
        """记录应用停止"""
        logger = self.get_logger("app")
        logger.info(f"{self.app_name} 应用停止")

    def log_performance(self, operation: str, duration: float, extra_data: Optional[Dict] = None):
        """记录性能数据"""
        logger = self.get_logger("performance")

        perf_data = {
            "operation": operation,
            "duration_seconds": duration,
        }

        if extra_data:
            perf_data.update(extra_data)

        logger.info(f"性能统计: {operation} 耗时 {duration:.3f}s",
                   extra={'extra_data': perf_data})

    def log_download_progress(self, task_id: str, progress: Dict[str, Any]):
        """记录下载进度"""
        logger = self.get_logger("download")

        progress_data = {
            "task_id": task_id,
            **progress
        }

        logger.debug(f"下载进度: {task_id}", extra={'extra_data': progress_data})

    def log_error_with_context(self, logger_name: str, message: str,
                              context: Optional[Dict] = None, exc_info=None):
        """记录带上下文的错误信息"""
        logger = self.get_logger(logger_name)

        extra = {}
        if context:
            extra['extra_data'] = context

        logger.error(message, extra=extra, exc_info=exc_info)

    def get_log_stats(self) -> Dict[str, Any]:
        """获取日志统计信息"""
        stats = {}

        for log_type, log_file in self.log_files.items():
            if log_file.exists():
                stat = log_file.stat()
                stats[log_type] = {
                    "file_path": str(log_file),
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "line_count": self._count_lines(log_file)
                }
            else:
                stats[log_type] = {
                    "file_path": str(log_file),
                    "exists": False
                }

        return stats

    def _count_lines(self, file_path: Path) -> int:
        """计算文件行数"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def clean_old_logs(self, days: int = 30):
        """清理旧日志文件"""
        import time

        current_time = time.time()
        cutoff_time = current_time - (days * 24 * 60 * 60)

        cleaned_files = []

        for log_file in self.log_dir.glob("*.log*"):
            if log_file.stat().st_mtime < cutoff_time:
                try:
                    log_file.unlink()
                    cleaned_files.append(str(log_file))
                except Exception as e:
                    logger = self.get_logger("log_manager")
                    logger.error(f"清理日志文件失败 {log_file}: {e}")

        if cleaned_files:
            logger = self.get_logger("log_manager")
            logger.info(f"清理了 {len(cleaned_files)} 个旧日志文件")

        return cleaned_files

    def export_logs(self, output_file: str, log_type: str = "app",
                   start_time: Optional[datetime] = None,
                   end_time: Optional[datetime] = None):
        """
        导出日志

        Args:
            output_file: 输出文件路径
            log_type: 日志类型 (app, error, json)
            start_time: 开始时间
            end_time: 结束时间
        """
        if log_type not in self.log_files:
            raise ValueError(f"不支持的日志类型: {log_type}")

        log_file = self.log_files[log_type]
        if not log_file.exists():
            raise FileNotFoundError(f"日志文件不存在: {log_file}")

        exported_lines = []

        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                # 简单的时间过滤（可以根据需要改进）
                include_line = True

                if start_time or end_time:
                    # 这里可以添加更精确的时间过滤逻辑
                    pass

                if include_line:
                    exported_lines.append(line)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(exported_lines)

        logger = self.get_logger("log_manager")
        logger.info(f"日志已导出到: {output_file}，共 {len(exported_lines)} 行")


# 全局日志管理器实例
_log_manager = None


def get_log_manager(**kwargs) -> LogManager:
    """获取全局日志管理器实例"""
    global _log_manager
    if _log_manager is None:
        _log_manager = LogManager(**kwargs)
    return _log_manager


def get_logger(name: str) -> logging.Logger:
    """获取logger的便捷函数"""
    return get_log_manager().get_logger(name)


# 使用示例
if __name__ == "__main__":
    # 创建日志管理器
    log_manager = LogManager()

    # 获取不同模块的logger
    app_logger = log_manager.get_logger("app")
    download_logger = log_manager.get_logger("download")
    ui_logger = log_manager.get_logger("ui")

    # 记录系统信息
    log_manager.log_system_info()
    log_manager.log_app_start()

    # 测试不同级别的日志
    app_logger.debug("这是一个调试信息")
    app_logger.info("应用正常运行")
    app_logger.warning("这是一个警告")
    app_logger.error("这是一个错误")

    # 记录带额外数据的日志
    download_logger.info("下载任务开始", extra={
        'extra_data': {
            'task_id': 'task_001',
            'url': 'https://example.com/video.m3u8',
            'segments': 100
        }
    })

    # 记录性能数据
    log_manager.log_performance("video_merge", 15.5, {
        'input_files': 100,
        'output_size': 1024 * 1024 * 500
    })

    # 获取日志统计
    stats = log_manager.get_log_stats()
    print(f"日志统计: {stats}")

    log_manager.log_app_stop()