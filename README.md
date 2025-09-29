# M3U8下载器

一个高性能的M3U8视频下载工具，支持GUI界面、命令行模式和HTTP API，可与猫抓等浏览器扩展无缝集成。

## ✨ 主要特性

### 🎯 核心功能
- **智能M3U8解析**: 支持标准和master播放列表，自动选择最佳质量
- **AES-128解密**: 完整支持加密视频的解密处理
- **高性能下载**: 基于asyncio的异步多线程下载，支持动态并发控制
- **断点续传**: 支持暂停/恢复下载，智能处理网络中断
- **自动合并**: 使用FFmpeg自动合并TS片段为MP4格式

### 🖥️ 用户界面
- **现代化GUI**: 基于PyQt6的直观图形界面
- **实时进度**: 详细的下载进度、速度和ETA显示
- **任务管理**: 支持批量下载、暂停、恢复、删除操作
- **智能日志**: 多级别日志显示，支持搜索和过滤

### 🌐 API集成
- **HTTP API**: RESTful接口，支持远程控制
- **猫抓集成**: 完美支持猫抓等浏览器扩展
- **实时同步**: GUI和API任务实时同步显示
- **JSON配置**: 灵活的配置管理系统

### ⚙️ 高级特性
- **性能优化**: 内存管理、速度限制、智能重试
- **监控系统**: 完整的性能监控和统计分析
- **配置管理**: 支持配置备份、恢复和验证
- **跨平台**: 支持Windows、macOS、Linux

## 📦 安装要求

### 系统要求
- Python 3.8+
- Windows 10/11, macOS 10.14+, Linux

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/your-repo/m3u8-downloader.git
cd m3u8-downloader
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **安装FFmpeg**
- Windows: 下载 https://ffmpeg.org/download.html 并添加到PATH
- macOS: `brew install ffmpeg`
- Linux: `sudo apt-get install ffmpeg`

## 🚀 使用方法

### 默认模式（GUI + HTTP服务器）
```bash
python main.py
```
这将同时启动图形界面和HTTP服务器，支持猫抓等扩展调用。

### 仅GUI模式
```bash
python main.py --gui
```

### 仅HTTP服务器模式
```bash
python main.py --server
```

### 命令行下载
```bash
# 基础下载
python main.py --cli --url "https://example.com/video.m3u8"

# 完整参数
python main.py --cli --url "https://example.com/video.m3u8" \
  --output "./downloads" --filename "my_video" \
  --concurrent 16 --speed-limit 2048
```

### 查看配置信息
```bash
python main.py --config
```

## 🔧 配置文件

配置文件位置：
- Windows: `%USERPROFILE%\.m3u8_downloader\config.json`
- macOS/Linux: `~/.m3u8_downloader/config.json`

主要配置项：

```json
{
  "download": {
    "max_concurrent": 8,
    "max_speed_kbps": null,
    "timeout": 30,
    "retry_count": 3,
    "default_output_path": "./downloads"
  },
  "network": {
    "user_agent": "Mozilla/5.0...",
    "proxy_url": null,
    "custom_headers": {}
  },
  "ffmpeg": {
    "ffmpeg_path": null,
    "default_quality": "medium",
    "video_codec": "libx264"
  }
}
```

## 🌐 猫抓集成

### 使用方法

1. **启动下载器**
```bash
python main.py
```
默认HTTP服务器将在 `http://127.0.0.1:8080` 启动。

2. **配置猫抓外部下载工具**
   - 名称：`M3U8下载器`
   - 命令：
```bash
curl -X POST http://127.0.0.1:8080/api/add-download -H "Content-Type: application/json" -d "{\"url\":\"%URL%\",\"filename\":\"%FILENAME%\"}"
```

3. **或者使用浏览器控制台**
```javascript
fetch('http://127.0.0.1:8080/api/add-download', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    url: 'M3U8链接',
    filename: '文件名'
  })
}).then(r => r.json()).then(d => console.log(d));
```

### API接口

- `GET /api/status` - 获取服务器状态
- `POST /api/add-download` - 添加下载任务
- `GET /api/tasks` - 获取所有任务状态
- `GET /api/tasks/{task_id}` - 获取特定任务信息

## 📖 项目结构

```
m3u8_downloader/
├── main.py                    # 主程序入口
├── requirements.txt           # 项目依赖
├── README.md                  # 项目说明
├── 猫抓集成说明.md            # 猫抓集成详细说明
├── downloads/                 # 默认下载目录
└── src/                       # 源代码
    ├── core/                  # 核心功能模块
    │   ├── downloader.py      # 异步下载器
    │   ├── http_server.py     # HTTP API服务器
    │   ├── m3u8_parser.py     # M3U8解析器
    │   ├── optimized_downloader.py  # 优化下载器
    │   └── video_processor.py # 视频处理器
    ├── gui/                   # GUI界面
    │   ├── main_window.py     # 主窗口
    │   └── enhanced_main_window.py  # 增强主窗口
    └── utils/                 # 工具模块
        ├── config.py          # 配置管理
        ├── logger.py          # 日志系统
        ├── task_manager.py    # 全局任务管理器
        ├── memory_manager.py  # 内存管理
        ├── performance_monitor.py  # 性能监控
        ├── smart_retry.py     # 智能重试
        └── error_handling.py  # 错误处理
```

## 🛠️ 打包为EXE

使用PyInstaller打包为单文件executable：

```bash
# 安装PyInstaller
pip install pyinstaller

# 打包为单文件EXE（无控制台窗口）
pyinstaller --onefile --noconsole --icon=src/icon/app.ico main.py

# 打包后的文件在 dist/ 目录中
```

打包选项说明：
- `--onefile`: 打包为单个文件
- `--noconsole`: 不显示控制台窗口（GUI程序）
- `--icon`: 指定程序图标

## 🔧 故障排除

### 常见问题

**1. FFmpeg相关错误**
```
错误: 未找到FFmpeg
解决方案:
1. 下载安装FFmpeg
2. 添加到系统PATH
3. 或在配置文件中指定ffmpeg_path
```

**2. 下载失败或速度慢**
```
解决方案:
1. 检查网络连接和防火墙设置
2. 尝试使用代理服务器
3. 降低并发连接数（max_concurrent）
4. 增加超时时间（timeout）
```

**3. 猫抓无法连接**
```
错误: HTTP服务器连接失败
解决方案:
1. 确保下载器程序正在运行
2. 检查端口8080是否被占用
3. 检查防火墙设置
4. 尝试重启程序
```

**4. GUI界面无响应**
```
解决方案:
1. 检查PyQt6是否正确安装
2. 更新显卡驱动程序
3. 尝试使用 --debug 参数查看详细日志
```

### 日志文件位置
- 应用日志: `~/.m3u8_downloader/logs/m3u8downloader.log`
- 错误日志: `~/.m3u8_downloader/logs/m3u8downloader_error.log`
- JSON日志: `~/.m3u8_downloader/logs/m3u8downloader.json.log`

## 🤝 开发贡献

### 开发环境
```bash
git clone https://github.com/your-repo/m3u8-downloader.git
cd m3u8-downloader
pip install -r requirements.txt
```

### 测试运行
```bash
# 运行基本功能测试
python main.py --config

# 运行命令行测试
python main.py --cli --url "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"
```

## 📄 许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。

## 🙏 致谢

- [FFmpeg](https://ffmpeg.org/) - 强大的音视频处理工具
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) - 优秀的Python GUI框架
- [aiohttp](https://aiohttp.readthedocs.io/) - 异步HTTP客户端/服务器框架

---

**免责声明**: 本工具仅供学习和研究使用，请遵守相关法律法规，尊重内容版权。