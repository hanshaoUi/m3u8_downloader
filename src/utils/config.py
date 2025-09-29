import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
import logging


@dataclass
class DownloadConfig:
    max_concurrent: int = 16  # 增加并发数以提高下载速度
    max_speed_kbps: Optional[int] = None  # 限速 KB/s，None为不限速
    timeout: int = 30
    retry_count: int = 5  # 增加重试次数
    retry_delay: float = 0.5  # 重试延迟基数(秒)
    max_retry_delay: float = 10.0  # 最大重试延迟(秒)
    default_output_path: str = "./downloads"
    auto_merge: bool = True
    delete_temp_files: bool = True
    adaptive_concurrent: bool = True  # 自适应并发数


@dataclass
class NetworkConfig:
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    custom_headers: Dict[str, str] = None

    def __post_init__(self):
        if self.custom_headers is None:
            self.custom_headers = {}


@dataclass
class UIConfig:
    theme: str = "light"  # light, dark
    language: str = "zh-CN"  # zh-CN, en-US
    auto_minimize: bool = True
    check_updates: bool = True
    show_notifications: bool = True


@dataclass
class FFmpegConfig:
    ffmpeg_path: Optional[str] = None
    default_quality: str = "medium"  # high, medium, low
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    preset: str = "medium"  # ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow
    crf: int = 23  # 0-51, lower is better quality


@dataclass
class BrowserConfig:
    server_port: int = 8081
    auto_start_server: bool = True
    allowed_origins: list = None

    def __post_init__(self):
        if self.allowed_origins is None:
            self.allowed_origins = ["chrome-extension://*"]


@dataclass
class AppConfig:
    download: DownloadConfig = None
    network: NetworkConfig = None
    ui: UIConfig = None
    ffmpeg: FFmpegConfig = None
    browser: BrowserConfig = None

    def __post_init__(self):
        if self.download is None:
            self.download = DownloadConfig()
        if self.network is None:
            self.network = NetworkConfig()
        if self.ui is None:
            self.ui = UIConfig()
        if self.ffmpeg is None:
            self.ffmpeg = FFmpegConfig()
        if self.browser is None:
            self.browser = BrowserConfig()


class ConfigManager:
    def __init__(self, config_dir: Optional[str] = None):
        """
        配置管理器

        Args:
            config_dir: 配置文件目录，如果为None则使用默认位置
        """
        if config_dir is None:
            # 使用用户目录下的配置文件夹
            self.config_dir = Path.home() / ".m3u8_downloader"
        else:
            self.config_dir = Path(config_dir)

        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.json"

        self._config: Optional[AppConfig] = None
        self._logger = logging.getLogger(__name__)

    def load_config(self) -> AppConfig:
        """加载配置文件"""
        if self._config is not None:
            return self._config

        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 递归创建配置对象
                self._config = self._dict_to_config(data)
                self._logger.info("配置文件加载成功")
            else:
                self._config = AppConfig()
                self.save_config()
                self._logger.info("创建默认配置文件")

        except Exception as e:
            self._logger.error(f"加载配置文件失败: {e}")
            self._config = AppConfig()

        return self._config

    def save_config(self) -> bool:
        """保存配置文件"""
        if self._config is None:
            return False

        try:
            data = self._config_to_dict(self._config)

            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self._logger.info("配置文件保存成功")
            return True

        except Exception as e:
            self._logger.error(f"保存配置文件失败: {e}")
            return False

    def get_config(self) -> AppConfig:
        """获取当前配置"""
        if self._config is None:
            return self.load_config()
        return self._config

    def update_config(self, **kwargs) -> bool:
        """更新配置项"""
        try:
            config = self.get_config()

            for key, value in kwargs.items():
                if hasattr(config, key):
                    if isinstance(value, dict):
                        # 更新嵌套配置
                        nested_config = getattr(config, key)
                        for nested_key, nested_value in value.items():
                            if hasattr(nested_config, nested_key):
                                setattr(nested_config, nested_key, nested_value)
                    else:
                        setattr(config, key, value)

            return self.save_config()

        except Exception as e:
            self._logger.error(f"更新配置失败: {e}")
            return False

    def reset_config(self) -> bool:
        """重置为默认配置"""
        try:
            self._config = AppConfig()
            return self.save_config()
        except Exception as e:
            self._logger.error(f"重置配置失败: {e}")
            return False

    def backup_config(self, backup_name: Optional[str] = None) -> bool:
        """备份配置文件"""
        try:
            if backup_name is None:
                from datetime import datetime
                backup_name = f"config_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            backup_file = self.config_dir / backup_name

            if self.config_file.exists():
                import shutil
                shutil.copy2(self.config_file, backup_file)
                self._logger.info(f"配置文件已备份到: {backup_file}")
                return True
            else:
                self._logger.warning("配置文件不存在，无法备份")
                return False

        except Exception as e:
            self._logger.error(f"备份配置文件失败: {e}")
            return False

    def restore_config(self, backup_file: str) -> bool:
        """从备份恢复配置"""
        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                backup_path = self.config_dir / backup_file

            if not backup_path.exists():
                self._logger.error(f"备份文件不存在: {backup_file}")
                return False

            import shutil
            shutil.copy2(backup_path, self.config_file)

            # 重新加载配置
            self._config = None
            self.load_config()

            self._logger.info(f"配置文件已从备份恢复: {backup_file}")
            return True

        except Exception as e:
            self._logger.error(f"恢复配置文件失败: {e}")
            return False

    def get_config_info(self) -> Dict[str, Any]:
        """获取配置文件信息"""
        info = {
            "config_dir": str(self.config_dir),
            "config_file": str(self.config_file),
            "config_exists": self.config_file.exists()
        }

        if self.config_file.exists():
            stat = self.config_file.stat()
            info.update({
                "file_size": stat.st_size,
                "modified_time": stat.st_mtime,
                "is_readable": os.access(self.config_file, os.R_OK),
                "is_writable": os.access(self.config_file, os.W_OK)
            })

        return info

    def _dict_to_config(self, data: Dict[str, Any]) -> AppConfig:
        """将字典转换为配置对象"""
        config = AppConfig()

        if 'download' in data:
            config.download = DownloadConfig(**data['download'])

        if 'network' in data:
            config.network = NetworkConfig(**data['network'])

        if 'ui' in data:
            config.ui = UIConfig(**data['ui'])

        if 'ffmpeg' in data:
            config.ffmpeg = FFmpegConfig(**data['ffmpeg'])

        if 'browser' in data:
            config.browser = BrowserConfig(**data['browser'])

        return config

    def _config_to_dict(self, config: AppConfig) -> Dict[str, Any]:
        """将配置对象转换为字典"""
        return {
            'download': asdict(config.download),
            'network': asdict(config.network),
            'ui': asdict(config.ui),
            'ffmpeg': asdict(config.ffmpeg),
            'browser': asdict(config.browser)
        }

    def validate_config(self) -> Dict[str, Any]:
        """验证配置有效性"""
        config = self.get_config()
        issues = []

        # 验证下载配置
        if config.download.max_concurrent <= 0:
            issues.append("下载并发数必须大于0")

        if config.download.timeout <= 0:
            issues.append("超时时间必须大于0")

        if config.download.retry_count < 0:
            issues.append("重试次数不能为负数")

        # 验证网络配置
        if config.network.proxy_url and not config.network.proxy_url.startswith(('http://', 'https://', 'socks5://')):
            issues.append("代理URL格式不正确")

        # 验证FFmpeg配置
        if config.ffmpeg.crf < 0 or config.ffmpeg.crf > 51:
            issues.append("CRF值必须在0-51之间")

        # 验证浏览器配置
        if config.browser.server_port <= 0 or config.browser.server_port > 65535:
            issues.append("服务器端口必须在1-65535之间")

        return {
            "valid": len(issues) == 0,
            "issues": issues
        }


# 全局配置管理器实例
_config_manager = None


def get_config_manager(config_dir: Optional[str] = None) -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_dir)
    return _config_manager


def get_config() -> AppConfig:
    """获取当前配置"""
    return get_config_manager().get_config()


# 使用示例
if __name__ == "__main__":
    # 创建配置管理器
    config_manager = ConfigManager()

    # 加载配置
    config = config_manager.load_config()
    print(f"当前配置: {config}")

    # 更新配置
    config_manager.update_config(
        download={
            "max_concurrent": 16,
            "max_speed_kbps": 2048
        }
    )

    # 验证配置
    validation = config_manager.validate_config()
    print(f"配置验证结果: {validation}")

    # 获取配置信息
    info = config_manager.get_config_info()
    print(f"配置文件信息: {info}")

    # 备份配置
    config_manager.backup_config()