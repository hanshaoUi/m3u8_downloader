import asyncio
import json
import uuid
from aiohttp import web, web_request
from aiohttp.web_response import Response
from typing import Dict, Any, Optional
import logging
from pathlib import Path
import re
from .downloader import AsyncDownloader
from ..utils.config import get_config
from ..utils.logger import get_logger
from ..utils.task_manager import get_task_manager


class HTTPServer:
    """HTTP服务器，用于接收猫抓等外部工具的调用"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.logger = get_logger("http_server")
        self.task_manager = get_task_manager()

        self.setup_routes()

    def setup_routes(self):
        """设置路由"""
        # CORS支持
        self.app.middlewares.append(self.cors_handler)

        # API路由
        self.app.router.add_post('/api/add-download', self.add_download_handler)
        self.app.router.add_get('/api/status', self.status_handler)
        self.app.router.add_get('/api/tasks', self.tasks_handler)
        self.app.router.add_post('/api/control/{task_id}/{action}', self.control_handler)

        # 静态文件（用于简单的Web界面）
        self.app.router.add_get('/', self.index_handler)

    @web.middleware
    async def cors_handler(self, request: web_request.Request, handler):
        """CORS中间件"""
        if request.method == 'OPTIONS':
            response = web.Response()
        else:
            response = await handler(request)

        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    async def index_handler(self, request: web_request.Request) -> Response:
        """主页处理器，提供简单的Web界面"""
        html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>M3U8下载器 - 接口调用</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .container { max-width: 800px; margin: 0 auto; }
        .section { margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
        input, button { padding: 8px; margin: 5px; }
        input[type="text"] { width: 300px; }
        button { background: #007bff; color: white; border: none; border-radius: 3px; cursor: pointer; }
        button:hover { background: #0056b3; }
        .status { padding: 10px; margin: 10px 0; border-radius: 3px; }
        .success { background: #d4edda; color: #155724; }
        .error { background: #f8d7da; color: #721c24; }
        pre { background: #f8f9fa; padding: 10px; border-radius: 3px; overflow-x: auto; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎬 M3U8下载器 HTTP接口</h1>

        <div class="section">
            <h3>📥 添加下载任务</h3>
            <p>猫抓插件可以通过POST请求调用此接口添加下载任务</p>
            <input type="text" id="urlInput" placeholder="输入M3U8链接" />
            <input type="text" id="filenameInput" placeholder="文件名（可选）" />
            <button onclick="addDownload()">添加下载</button>
            <div id="addResult"></div>
        </div>

        <div class="section">
            <h3>📊 服务状态</h3>
            <button onclick="checkStatus()">检查状态</button>
            <button onclick="getTasks()">获取任务列表</button>
            <div id="statusResult"></div>
        </div>

        <div class="section">
            <h3>🔧 猫抓集成说明</h3>
            <p><strong>方法1：直接调用</strong></p>
            <pre>fetch('http://127.0.0.1:8080/api/add-download', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    url: 'M3U8链接',
    filename: '文件名'
  })
})</pre>

            <p><strong>方法2：浏览器地址栏</strong></p>
            <pre>http://127.0.0.1:8080/api/add-download?url=M3U8链接&filename=文件名</pre>
        </div>
    </div>

    <script>
        async function addDownload() {
            const url = document.getElementById('urlInput').value;
            const filename = document.getElementById('filenameInput').value;

            if (!url) {
                showResult('addResult', '请输入URL', 'error');
                return;
            }

            try {
                const response = await fetch('/api/add-download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url, filename })
                });

                const result = await response.json();

                if (result.success) {
                    showResult('addResult', `下载任务已添加：${result.task_id}`, 'success');
                    document.getElementById('urlInput').value = '';
                    document.getElementById('filenameInput').value = '';
                } else {
                    showResult('addResult', `添加失败：${result.error}`, 'error');
                }
            } catch (error) {
                showResult('addResult', `请求失败：${error.message}`, 'error');
            }
        }

        async function checkStatus() {
            try {
                const response = await fetch('/api/status');
                const result = await response.json();
                showResult('statusResult', `<pre>${JSON.stringify(result, null, 2)}</pre>`, 'success');
            } catch (error) {
                showResult('statusResult', `请求失败：${error.message}`, 'error');
            }
        }

        async function getTasks() {
            try {
                const response = await fetch('/api/tasks');
                const result = await response.json();
                showResult('statusResult', `<pre>${JSON.stringify(result, null, 2)}</pre>`, 'success');
            } catch (error) {
                showResult('statusResult', `请求失败：${error.message}`, 'error');
            }
        }

        function showResult(elementId, message, type) {
            const element = document.getElementById(elementId);
            element.innerHTML = `<div class="status ${type}">${message}</div>`;
        }
    </script>
</body>
</html>
        """
        return web.Response(text=html, content_type='text/html')

    async def add_download_handler(self, request: web_request.Request) -> Response:
        """添加下载任务"""
        try:
            # 支持GET和POST请求
            if request.method == 'GET':
                url = request.query.get('url')
                filename = request.query.get('filename', '')
            else:
                data = await request.json()

                # 打印接收到的原始数据
                self.logger.info(f"接收到的原始数据: {data}")

                # 检查是否是猫抓格式的数据
                if 'action' in data and data.get('action') == 'catch':
                    # 猫抓格式: {"action": "catch", "data": {...}, "tabId": "..."}
                    catch_data = data.get('data', {})
                    url = catch_data.get('url')
                    # 尝试多个可能的文件名字段
                    filename = (catch_data.get('title') or
                              catch_data.get('fileName') or
                              catch_data.get('name') or '')
                    filename = re.sub(r'[\\/:*?"<>|]', '', filename)
                    self.logger.info(f"猫抓格式数据 - URL: {url}, 文件名: {filename}")
                    self.logger.info(f"猫抓data部分: {catch_data}")
                else:
                    # 普通格式: {"url": "...", "filename": "..."}
                    url = data.get('url')
                    filename = data.get('filename', '')
                    filename = re.sub(r'[\\/:*?"<>|]', '', filename)
                    self.logger.info(f"普通格式数据 - URL: {url}, 文件名: {filename}")

            if not url:
                return web.json_response({
                    'success': False,
                    'error': '缺少URL参数'
                }, status=400)

            # 验证URL格式
            if not (url.startswith('http://') or url.startswith('https://')):
                return web.json_response({
                    'success': False,
                    'error': 'URL格式不正确'
                }, status=400)

            # 生成任务ID和文件名
            task_id = str(uuid.uuid4())
            if not filename:
                filename = f"video_{task_id[:8]}"

            # 获取配置
            config = get_config()

            # 使用全局任务管理器
            task_id = await self.task_manager.add_download_task(
                url, config.download.default_output_path, filename
            )

            # 自动开始下载
            await self.task_manager.start_download(task_id)

            self.logger.info(f"通过HTTP接口添加下载任务: {url}")

            return web.json_response({
                'success': True,
                'task_id': task_id,
                'filename': filename,
                'message': '下载任务已添加并开始下载'
            })

        except Exception as e:
            self.logger.error(f"添加下载任务失败: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def status_handler(self, request: web_request.Request) -> Response:
        """获取服务状态"""
        try:
            config = get_config()

            status = {
                'status': 'running',
                'version': '1.0',
                'downloader_ready': True,  # 使用全局任务管理器，总是准备就绪
                'config': {
                    'max_concurrent': config.download.max_concurrent,
                    'default_output_path': config.download.default_output_path,
                    'timeout': config.download.timeout
                },
                'server': {
                    'host': self.host,
                    'port': self.port
                }
            }

            return web.json_response(status)

        except Exception as e:
            self.logger.error(f"获取状态失败: {e}", exc_info=True)
            return web.json_response({
                'status': 'error',
                'error': str(e)
            }, status=500)

    async def tasks_handler(self, request: web_request.Request) -> Response:
        """获取下载任务列表"""
        try:
            tasks = self.task_manager.get_all_tasks()

            # 转换为可序列化的格式
            task_list = []
            for task_id, task in tasks.items():
                task_info = {
                    'task_id': task_id,
                    'url': task.url,
                    'filename': task.filename,
                    'status': task.progress.status,
                    'progress': {
                        'total_segments': task.progress.total_segments,
                        'completed_segments': task.progress.completed_segments,
                        'failed_segments': task.progress.failed_segments,
                        'speed': task.progress.speed,
                        'eta': task.progress.eta
                    },
                    'created_time': task.created_time,
                    'start_time': task.start_time,
                    'end_time': task.end_time
                }
                task_list.append(task_info)

            return web.json_response({
                'success': True,
                'tasks': task_list,
                'total': len(task_list)
            })

        except Exception as e:
            self.logger.error(f"获取任务列表失败: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)

    async def control_handler(self, request: web_request.Request) -> Response:
        """控制下载任务（暂停/恢复/取消）"""
        try:
            task_id = request.match_info['task_id']
            action = request.match_info['action']

            if action == 'pause':
                await self.task_manager.pause_download(task_id)
                message = '任务已暂停'
            elif action == 'resume':
                await self.task_manager.resume_download(task_id)
                message = '任务已恢复'
            elif action == 'cancel':
                # TODO: 实现取消功能
                message = '任务取消功能待实现'
            else:
                return web.json_response({
                    'success': False,
                    'error': f'不支持的操作: {action}'
                }, status=400)

            self.logger.info(f"任务控制: {task_id} - {action}")

            return web.json_response({
                'success': True,
                'task_id': task_id,
                'action': action,
                'message': message
            })

        except Exception as e:
            self.logger.error(f"任务控制失败: {e}", exc_info=True)
            return web.json_response({
                'success': False,
                'error': str(e)
            }, status=500)


    async def start(self):
        """启动HTTP服务器"""
        try:
            # 启动任务管理器
            self.task_manager.start()

            # 启动服务器
            runner = web.AppRunner(self.app)
            await runner.setup()

            site = web.TCPSite(runner, self.host, self.port)
            await site.start()

            self.logger.info(f"HTTP服务器已启动: http://{self.host}:{self.port}")
            print(f"HTTP服务器已启动: http://{self.host}:{self.port}")
            print("猫抓可以通过以下接口调用:")
            print(f"  添加下载: POST http://{self.host}:{self.port}/api/add-download")
            print(f"  查看状态: GET  http://{self.host}:{self.port}/api/status")
            print(f"  管理界面: http://{self.host}:{self.port}/")

            # 保持服务器运行
            while True:
                await asyncio.sleep(1)

        except Exception as e:
            self.logger.error(f"服务器启动失败: {e}", exc_info=True)
            raise

    async def stop(self):
        """停止HTTP服务器"""
        self.task_manager.stop()
        self.logger.info("HTTP服务器已停止")


# 使用示例
async def main():
    server = HTTPServer(host="127.0.0.1", port=8080)
    try:
        await server.start()
    except KeyboardInterrupt:
        print("\n服务器停止中...")
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())