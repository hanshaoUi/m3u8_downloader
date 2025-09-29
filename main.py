#!/usr/bin/env python3
"""
M3U8下载器主程序
支持命令行和GUI两种模式
"""

import sys
import os
import argparse
import asyncio
from pathlib import Path

# 检测是否为PyInstaller打包的EXE环境
def is_running_as_exe():
    """检测是否在PyInstaller打包的EXE中运行"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

# 获取资源文件路径（兼容EXE环境）
def get_resource_path(relative_path):
    """获取资源文件的绝对路径，兼容PyInstaller打包环境"""
    if is_running_as_exe():
        # PyInstaller打包环境下的临时目录
        base_path = sys._MEIPASS
    else:
        # 开发环境
        base_path = os.path.dirname(__file__)
    return os.path.join(base_path, relative_path)

# 添加src目录到Python路径
if not is_running_as_exe():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
else:
    # EXE环境下，模块应该已经打包进去了
    pass

from src.utils.logger import get_log_manager, get_logger
from src.utils.config import get_config_manager, get_config


def setup_logging():
    """设置日志系统"""
    log_manager = get_log_manager(app_name="M3U8Downloader")
    log_manager.log_app_start()
    log_manager.log_system_info()
    return log_manager


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="M3U8视频下载器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py                                    # 启动GUI界面
  python main.py --cli --url URL                    # 命令行下载
  python main.py --server                           # 仅启动HTTP服务器
  python main.py --config                          # 显示配置信息
        """
    )

    parser.add_argument('--cli', action='store_true',
                       help='使用命令行模式')

    parser.add_argument('--gui', action='store_true',
                       help='使用GUI模式 (默认)')

    parser.add_argument('--server', action='store_true',
                       help='仅启动HTTP服务器（用于浏览器扩展）')

    parser.add_argument('--both', action='store_true',
                       help='同时启动GUI和HTTP服务器')

    parser.add_argument('--url', type=str,
                       help='要下载的M3U8链接')

    parser.add_argument('--output', '-o', type=str,
                       help='输出目录')

    parser.add_argument('--filename', '-f', type=str,
                       help='输出文件名')

    parser.add_argument('--concurrent', '-c', type=int,
                       help='并发下载数')

    parser.add_argument('--speed-limit', '-s', type=int,
                       help='速度限制 (KB/s)')

    parser.add_argument('--config', action='store_true',
                       help='显示配置信息')

    parser.add_argument('--version', action='version',
                       version='M3U8下载器 v1.0')

    parser.add_argument('--debug', action='store_true',
                       help='启用调试模式')

    return parser.parse_args()


async def cli_download(args):
    """命令行下载模式"""
    if not args.url:
        print("错误: 命令行模式需要指定 --url 参数")
        sys.exit(1)

    logger = get_logger("cli")
    config = get_config()

    # 覆盖配置参数
    if args.output:
        config.download.default_output_path = args.output
    if args.concurrent:
        config.download.max_concurrent = args.concurrent
    if args.speed_limit:
        config.download.max_speed_kbps = args.speed_limit

    try:
        from src.core.downloader import AsyncDownloader
        import uuid

        async with AsyncDownloader(
            max_concurrent=config.download.max_concurrent,
            max_speed=config.download.max_speed_kbps,
            timeout=config.download.timeout,
            retry_count=config.download.retry_count
        ) as downloader:

            # 添加进度回调
            def on_progress(task_id: str, progress):
                percent = (progress.completed_segments / progress.total_segments) * 100
                print(f"\r进度: {percent:.1f}% ({progress.completed_segments}/{progress.total_segments}) "
                      f"速度: {progress.speed:.1f} KB/s", end='', flush=True)

            def on_complete(task_id: str, task):
                print(f"\n✅ 下载完成: {task.filename}")
                logger.info(f"下载完成: {task.filename}")

            def on_error(task_id: str, error):
                print(f"\n❌ 下载失败: {error}")
                logger.error(f"下载失败: {error}")

            downloader.add_progress_callback(on_progress)
            downloader.add_complete_callback(on_complete)
            downloader.add_error_callback(on_error)

            # 添加下载任务
            task_id = str(uuid.uuid4())
            filename = args.filename or f"video_{task_id[:8]}"

            print(f"开始下载: {args.url}")
            logger.info(f"开始下载: {args.url}")

            task = await downloader.add_download_task(
                task_id, args.url, config.download.default_output_path, filename
            )

            await downloader.start_download(task_id)

            # 等待下载完成
            while task.progress.status in ["waiting", "downloading"]:
                await asyncio.sleep(1)

            if task.progress.status == "completed":
                print(f"\n下载成功完成!")
                return 0
            else:
                print(f"\n下载失败: {task.progress.status}")
                return 1

    except Exception as e:
        logger.error(f"CLI下载失败: {e}", exc_info=True)
        print(f"下载失败: {e}")
        return 1


def start_gui():
    """启动GUI界面"""
    try:
        from src.gui.main_window import main
        return main()
    except ImportError as e:
        logger = get_logger("main")
        logger.error(f"GUI启动失败: {e}")
        print("GUI启动失败: 缺少PyQt6依赖")
        print("请运行: pip install PyQt6")
        return 1


def start_both():
    """同时启动GUI和HTTP服务器"""
    import threading
    import time

    logger = get_logger("both")
    config = get_config()

    def run_server():
        """在后台线程中运行HTTP服务器"""
        async def server_main():
            try:
                from src.core.http_server import HTTPServer
                server = HTTPServer(host="127.0.0.1", port=config.browser.server_port)
                await server.start()
            except Exception as e:
                logger.error(f"HTTP服务器启动失败: {e}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server_main())

    try:
        # 启动HTTP服务器（后台线程）
        print("正在启动HTTP服务器...")
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # 等待服务器启动
        time.sleep(2)

        # 启动GUI（主线程）
        print("正在启动GUI界面...")
        from src.gui.main_window import M3U8DownloaderGUI
        from PyQt6.QtWidgets import QApplication

        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)

        window = M3U8DownloaderGUI()

        # 更新服务器状态显示
        window.update_server_status("运行中", config.browser.server_port)
        window.log_message(f"HTTP服务器已启动，端口: {config.browser.server_port}")
        window.log_message("猫抓可通过 http://127.0.0.1:8080/api/add-download 调用")

        window.show()

        # 程序退出时保存设置
        app.aboutToQuit.connect(window.save_settings)

        return app.exec()

    except ImportError as e:
        logger.error(f"GUI启动失败: {e}")
        print("GUI启动失败: 缺少PyQt6依赖")
        print("请运行: pip install PyQt6")
        return 1
    except Exception as e:
        logger.error(f"启动失败: {e}")
        print(f"启动失败: {e}")
        return 1


async def start_server():
    """启动HTTP服务器"""
    logger = get_logger("server")
    config = get_config()

    try:
        from src.core.http_server import HTTPServer

        server = HTTPServer(
            host="127.0.0.1",
            port=config.browser.server_port
        )

        print(f"HTTP服务器启动在端口 {config.browser.server_port}")
        print("按 Ctrl+C 停止服务器")

        await server.start()

    except ImportError:
        logger.error("HTTP服务器模块未实现")
        print("HTTP服务器功能尚未实现")
        return 1
    except Exception as e:
        logger.error(f"服务器启动失败: {e}", exc_info=True)
        print(f"服务器启动失败: {e}")
        return 1


def show_config_info():
    """显示配置信息"""
    config_manager = get_config_manager()
    config = config_manager.get_config()
    config_info = config_manager.get_config_info()
    validation = config_manager.validate_config()

    print("M3U8下载器配置信息")
    print("=" * 50)

    print(f"\n配置文件信息:")
    print(f"  配置目录: {config_info['config_dir']}")
    print(f"  配置文件: {config_info['config_file']}")
    print(f"  文件存在: {'是' if config_info['config_exists'] else '否'}")

    if config_info['config_exists']:
        print(f"  文件大小: {config_info['file_size']} 字节")
        print(f"  可读: {'是' if config_info['is_readable'] else '否'}")
        print(f"  可写: {'是' if config_info['is_writable'] else '否'}")

    print(f"\n下载配置:")
    print(f"  最大并发: {config.download.max_concurrent}")
    print(f"  速度限制: {config.download.max_speed_kbps or '无限制'} KB/s")
    print(f"  超时时间: {config.download.timeout}s")
    print(f"  重试次数: {config.download.retry_count}")
    print(f"  默认路径: {config.download.default_output_path}")

    print(f"\n网络配置:")
    print(f"  User-Agent: {config.network.user_agent[:50]}...")
    print(f"  代理服务器: {config.network.proxy_url or '未设置'}")

    print(f"\nFFmpeg配置:")
    print(f"  FFmpeg路径: {config.ffmpeg.ffmpeg_path or '自动检测'}")
    print(f"  默认质量: {config.ffmpeg.default_quality}")
    print(f"  视频编码: {config.ffmpeg.video_codec}")

    print(f"\n配置验证:")
    if validation['valid']:
        print("  配置有效")
    else:
        print("  配置存在问题:")
        for issue in validation['issues']:
            print(f"    - {issue}")

    # 显示日志信息
    log_manager = get_log_manager()
    log_stats = log_manager.get_log_stats()

    print(f"\n日志文件:")
    for log_type, stats in log_stats.items():
        if stats.get('exists', True):
            print(f"  {log_type}: {stats['size_mb']} MB ({stats['line_count']} 行)")
        else:
            print(f"  {log_type}: 文件不存在")


def main():
    """主函数"""
    # EXE环境下的特殊处理
    if is_running_as_exe():
        # 隐藏控制台窗口（如果有的话）
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        except:
            pass

    args = parse_arguments()

    # 设置日志级别
    log_manager = setup_logging()
    if args.debug:
        log_manager.set_level("DEBUG")

    logger = get_logger("main")

    try:
        # 根据参数选择运行模式
        if args.config:
            show_config_info()
            return 0

        elif args.cli:
            return asyncio.run(cli_download(args))

        elif args.server:
            return asyncio.run(start_server())

        elif args.both:
            return start_both()

        else:
            # 默认启动GUI和HTTP服务器
            return start_both()

    except KeyboardInterrupt:
        logger.info("用户中断程序")
        if not is_running_as_exe():
            print("\n程序已退出")
        return 0

    except Exception as e:
        logger.error(f"程序运行异常: {e}", exc_info=True)

        # EXE环境下显示错误对话框而不是控制台输出
        if is_running_as_exe():
            try:
                from PyQt6.QtWidgets import QApplication, QMessageBox
                import sys

                app = QApplication.instance()
                if app is None:
                    app = QApplication(sys.argv)

                msg = QMessageBox()
                msg.setIcon(QMessageBox.Icon.Critical)
                msg.setWindowTitle("M3U8下载器 - 错误")
                msg.setText(f"程序运行出错:\n\n{str(e)}")
                msg.setDetailedText(f"详细错误信息请查看日志文件")
                msg.exec()
            except:
                # 如果GUI也失败了，就不显示任何错误
                pass
        else:
            print(f"程序异常: {e}")
        return 1

    finally:
        log_manager.log_app_stop()


if __name__ == "__main__":
    sys.exit(main())