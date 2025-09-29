import sys
import os
import asyncio
import uuid
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                            QHBoxLayout, QLineEdit, QPushButton, QTableWidget,
                            QTableWidgetItem, QTextEdit, QFileDialog, QComboBox,
                            QProgressBar, QLabel, QSplitter, QHeaderView, QMessageBox,
                            QSystemTrayIcon, QMenu, QStatusBar, QDialog, QFormLayout,
                            QSpinBox, QCheckBox, QGroupBox, QTabWidget)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt, QSettings, QObject
from PyQt6.QtGui import QIcon, QFont, QAction
import json
import time

# 导入核心模块
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from src.core.downloader import AsyncDownloader, DownloadTask, DownloadProgress
from src.utils.task_manager import get_task_manager, TaskEvent, TaskEventData
from src.utils.config import get_config, get_config_manager


# DownloadWorker类已移除，使用全局任务管理器代替


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_manager = get_config_manager()
        self.config = self.config_manager.get_config()
        self.setWindowTitle('设置')
        self.setFixedSize(500, 400)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 创建选项卡
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        # 下载设置选项卡
        download_tab = self.create_download_tab()
        tab_widget.addTab(download_tab, '下载设置')

        # 网络设置选项卡
        network_tab = self.create_network_tab()
        tab_widget.addTab(network_tab, '网络设置')

        # 界面设置选项卡
        ui_tab = self.create_ui_tab()
        tab_widget.addTab(ui_tab, '界面设置')

        # 按钮
        button_layout = QHBoxLayout()

        save_button = QPushButton('保存')
        save_button.clicked.connect(self.save_settings)

        cancel_button = QPushButton('取消')
        cancel_button.clicked.connect(self.reject)

        reset_button = QPushButton('重置为默认')
        reset_button.clicked.connect(self.reset_settings)

        button_layout.addStretch()
        button_layout.addWidget(reset_button)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)

        layout.addLayout(button_layout)

    def create_download_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)

        # 下载设置组
        download_group = QGroupBox('下载配置')
        download_layout = QFormLayout(download_group)

        # 最大并发数
        self.max_concurrent_spin = QSpinBox()
        self.max_concurrent_spin.setRange(1, 32)
        self.max_concurrent_spin.setValue(self.config.download.max_concurrent)
        download_layout.addRow('最大并发线程数:', self.max_concurrent_spin)

        # 重试次数
        self.retry_count_spin = QSpinBox()
        self.retry_count_spin.setRange(1, 10)
        self.retry_count_spin.setValue(self.config.download.retry_count)
        download_layout.addRow('重试次数:', self.retry_count_spin)

        # 超时时间
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 300)
        self.timeout_spin.setSuffix(' 秒')
        self.timeout_spin.setValue(self.config.download.timeout)
        download_layout.addRow('超时时间:', self.timeout_spin)

        # 限速设置
        self.speed_limit_check = QCheckBox('启用下载限速')
        self.speed_limit_check.setChecked(self.config.download.max_speed_kbps is not None)
        download_layout.addRow(self.speed_limit_check)

        self.speed_limit_spin = QSpinBox()
        self.speed_limit_spin.setRange(100, 10000)
        self.speed_limit_spin.setSuffix(' KB/s')
        self.speed_limit_spin.setValue(self.config.download.max_speed_kbps or 1024)
        self.speed_limit_spin.setEnabled(self.speed_limit_check.isChecked())
        download_layout.addRow('下载速度限制:', self.speed_limit_spin)

        self.speed_limit_check.toggled.connect(self.speed_limit_spin.setEnabled)

        # 其他设置
        self.auto_merge_check = QCheckBox('自动合并视频片段')
        self.auto_merge_check.setChecked(self.config.download.auto_merge)
        download_layout.addRow(self.auto_merge_check)

        self.delete_temp_check = QCheckBox('下载完成后删除临时文件')
        self.delete_temp_check.setChecked(self.config.download.delete_temp_files)
        download_layout.addRow(self.delete_temp_check)

        layout.addWidget(download_group)
        return widget

    def create_network_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)

        # 网络设置组
        network_group = QGroupBox('网络配置')
        network_layout = QFormLayout(network_group)

        # User-Agent
        self.user_agent_edit = QLineEdit()
        self.user_agent_edit.setText(self.config.network.user_agent)
        network_layout.addRow('User-Agent:', self.user_agent_edit)

        # 代理设置
        self.proxy_check = QCheckBox('使用代理')
        self.proxy_check.setChecked(bool(self.config.network.proxy_url))
        network_layout.addRow(self.proxy_check)

        self.proxy_url_edit = QLineEdit()
        self.proxy_url_edit.setText(self.config.network.proxy_url or '')
        self.proxy_url_edit.setPlaceholderText('http://127.0.0.1:7890')
        self.proxy_url_edit.setEnabled(self.proxy_check.isChecked())
        network_layout.addRow('代理地址:', self.proxy_url_edit)

        self.proxy_check.toggled.connect(self.proxy_url_edit.setEnabled)

        layout.addWidget(network_group)
        return widget

    def create_ui_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)

        # 界面设置组
        ui_group = QGroupBox('界面配置')
        ui_layout = QFormLayout(ui_group)

        # 主题
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(['light', 'dark'])
        self.theme_combo.setCurrentText(self.config.ui.theme)
        ui_layout.addRow('主题:', self.theme_combo)

        # 语言
        self.language_combo = QComboBox()
        self.language_combo.addItems(['zh-CN', 'en-US'])
        self.language_combo.setCurrentText(self.config.ui.language)
        ui_layout.addRow('语言:', self.language_combo)

        # 其他设置
        self.auto_minimize_check = QCheckBox('启动时最小化到托盘')
        self.auto_minimize_check.setChecked(self.config.ui.auto_minimize)
        ui_layout.addRow(self.auto_minimize_check)

        self.check_updates_check = QCheckBox('启动时检查更新')
        self.check_updates_check.setChecked(self.config.ui.check_updates)
        ui_layout.addRow(self.check_updates_check)

        self.show_notifications_check = QCheckBox('显示下载完成通知')
        self.show_notifications_check.setChecked(self.config.ui.show_notifications)
        ui_layout.addRow(self.show_notifications_check)

        layout.addWidget(ui_group)
        return widget

    def save_settings(self):
        """保存设置"""
        try:
            # 更新下载配置
            self.config.download.max_concurrent = self.max_concurrent_spin.value()
            self.config.download.retry_count = self.retry_count_spin.value()
            self.config.download.timeout = self.timeout_spin.value()

            if self.speed_limit_check.isChecked():
                self.config.download.max_speed_kbps = self.speed_limit_spin.value()
            else:
                self.config.download.max_speed_kbps = None

            self.config.download.auto_merge = self.auto_merge_check.isChecked()
            self.config.download.delete_temp_files = self.delete_temp_check.isChecked()

            # 更新网络配置
            self.config.network.user_agent = self.user_agent_edit.text()

            if self.proxy_check.isChecked():
                self.config.network.proxy_url = self.proxy_url_edit.text()
            else:
                self.config.network.proxy_url = None

            # 更新界面配置
            self.config.ui.theme = self.theme_combo.currentText()
            self.config.ui.language = self.language_combo.currentText()
            self.config.ui.auto_minimize = self.auto_minimize_check.isChecked()
            self.config.ui.check_updates = self.check_updates_check.isChecked()
            self.config.ui.show_notifications = self.show_notifications_check.isChecked()

            # 保存配置
            if self.config_manager.save_config():
                # 如果是主题设置改变，立即应用新主题
                if hasattr(self.parent(), 'apply_theme'):
                    self.parent().apply_theme()

                QMessageBox.information(self, '设置', '设置已保存！\n主题设置已立即生效，其他设置可能需要重启程序后生效。')
                self.accept()
            else:
                QMessageBox.warning(self, '错误', '保存设置失败！')

        except Exception as e:
            QMessageBox.critical(self, '错误', f'保存设置时发生错误: {str(e)}')

    def reset_settings(self):
        """重置为默认设置"""
        reply = QMessageBox.question(self, '确认重置',
                                   '确定要重置所有设置为默认值吗？\n此操作不可撤销。',
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            if self.config_manager.reset_config():
                QMessageBox.information(self, '重置完成', '设置已重置为默认值！\n请重启程序使设置生效。')
                self.reject()
            else:
                QMessageBox.warning(self, '错误', '重置设置失败！')


class M3U8DownloaderGUI(QMainWindow):
    # 定义信号用于线程间通信
    task_added_signal = pyqtSignal(object)
    task_progress_signal = pyqtSignal(object)
    task_completed_signal = pyqtSignal(object)
    task_failed_signal = pyqtSignal(object)
    log_message_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.settings = QSettings('M3U8Downloader', 'Settings')
        self.tasks = {}  # task_id -> task_info
        self.task_manager = get_task_manager()

        self.init_ui()
        self.setup_signals()
        self.setup_task_manager()
        self.apply_theme()  # 应用主题
        self.load_settings()  # 在界面创建完成后恢复设置
        # 不再在GUI中启动HTTP服务器，应该由外部统一管理

    def setup_signals(self):
        """设置信号连接"""
        self.task_added_signal.connect(self.add_task_to_table_from_manager)
        self.task_progress_signal.connect(self.update_task_progress_from_manager)
        self.task_completed_signal.connect(self.update_task_completed_from_manager)
        self.task_failed_signal.connect(self.update_task_failed_from_manager)
        self.log_message_signal.connect(self.log_message_from_manager)

    def init_ui(self):
        self.setWindowTitle('M3U8下载器 v1.0')
        self.setGeometry(100, 100, 730, 800)
        self.setMinimumSize(600, 500)  # 设置最小尺寸，允许调节

        # 设置应用程序图标
        self.setup_icon()

        # 创建中央窗口
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # 创建菜单栏
        self.create_menubar()

        # 创建工具栏
        self.create_toolbar()

        # URL输入区域
        url_widget = self.create_url_input_section()
        layout.addWidget(url_widget)

        # 创建主分割器（任务列表和日志）
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(self.main_splitter)

        # 下载任务列表
        task_widget = self.create_task_list_section()
        self.main_splitter.addWidget(task_widget)

        # 日志输出区域
        log_widget = self.create_log_section()
        self.main_splitter.addWidget(log_widget)

        # 设置分割器属性，使其可调节并保存状态
        self.main_splitter.setChildrenCollapsible(False)  # 防止子控件被完全折叠
        self.main_splitter.setSizes([500, 200])  # 设置默认比例

        # 状态栏
        self.create_status_bar()

        # 系统托盘
        self.create_system_tray()

    def create_menubar(self):
        """创建菜单栏"""
        menubar = self.menuBar()

        # 视图菜单
        view_menu = menubar.addMenu('视图')

        # 工具栏显示/隐藏
        toolbar_action = QAction('显示工具栏', self, checkable=True)
        toolbar_action.setChecked(True)
        toolbar_action.triggered.connect(self.toggle_toolbar)
        view_menu.addAction(toolbar_action)

        # 状态栏显示/隐藏
        statusbar_action = QAction('显示状态栏', self, checkable=True)
        statusbar_action.setChecked(True)
        statusbar_action.triggered.connect(self.toggle_statusbar)
        view_menu.addAction(statusbar_action)

        view_menu.addSeparator()

        # 重置界面布局
        reset_layout_action = QAction('重置界面布局', self)
        reset_layout_action.triggered.connect(self.reset_layout)
        view_menu.addAction(reset_layout_action)

        # 工具菜单
        tools_menu = menubar.addMenu('工具')

        # 设置
        settings_action = QAction('设置', self)
        settings_action.triggered.connect(self.show_settings)
        tools_menu.addAction(settings_action)

        # 帮助菜单
        help_menu = menubar.addMenu('帮助')

        # 关于
        about_action = QAction('关于', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def toggle_toolbar(self, checked):
        """切换工具栏显示"""
        if hasattr(self, 'toolbar'):
            self.toolbar.setVisible(checked)

    def toggle_statusbar(self, checked):
        """切换状态栏显示"""
        if hasattr(self, 'status_bar'):
            self.status_bar.setVisible(checked)

    def reset_layout(self):
        """重置界面布局"""
        # 重置分割器
        if hasattr(self, 'main_splitter'):
            self.main_splitter.setSizes([500, 200])

        # 重置表格列宽
        if hasattr(self, 'task_table'):
            self.task_table.setColumnWidth(0, 250)  # 视频名称
            self.task_table.setColumnWidth(1, 80)   # 状态
            self.task_table.setColumnWidth(2, 150)  # 进度
            self.task_table.setColumnWidth(3, 80)   # 速度
            self.task_table.setColumnWidth(4, 90)   # 剩余时间
            self.task_table.setColumnWidth(5, 120)  # 操作

        QMessageBox.information(self, '提示', '界面布局已重置')

    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, '关于 M3U8下载器',
                         '<h3>M3U8下载器 v1.0</h3>'
                         '<p>一个高效的M3U8视频下载工具</p>'
                         '<p>支持多线程下载、断点续传、自动合并等功能</p>'
                         '<p>兼容猫抓浏览器扩展</p>')

    def create_toolbar(self):
        self.toolbar = self.addToolBar('主工具栏')

        # 开始下载
        start_action = QAction('🔄 开始下载', self)
        start_action.triggered.connect(self.start_selected_downloads)
        self.toolbar.addAction(start_action)

        # 暂停下载
        pause_action = QAction('⏸️ 暂停', self)
        pause_action.triggered.connect(self.pause_selected_downloads)
        self.toolbar.addAction(pause_action)

        # 删除任务
        delete_action = QAction('🗑️ 删除', self)
        delete_action.triggered.connect(self.delete_selected_tasks)
        self.toolbar.addAction(delete_action)
        self.toolbar.addSeparator()

        # 设置
        settings_action = QAction('⚙️ 设置', self)
        settings_action.triggered.connect(self.show_settings)
        self.toolbar.addAction(settings_action)

        # 帮助
        help_action = QAction('❓ 帮助', self)
        help_action.triggered.connect(self.show_help)
        self.toolbar.addAction(help_action)

        self.toolbar.addSeparator()

        # 退出
        exit_action = QAction('🚪 退出', self)
        exit_action.triggered.connect(self.force_exit_application)
        self.toolbar.addAction(exit_action)

    def create_url_input_section(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 标题
        title = QLabel('📺 URL输入区域')
        title.setFont(QFont('Microsoft YaHei', 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # URL输入
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('请输入M3U8链接...')
        self.url_input.returnPressed.connect(self.add_download_task)
        self.url_input.setMinimumHeight(35)  # 增加输入框高度

        paste_btn = QPushButton('📋')
        paste_btn.setToolTip('粘贴剪贴板')
        paste_btn.clicked.connect(self.paste_from_clipboard)
        paste_btn.setMinimumHeight(35)  # 增加按钮高度

        url_layout.addWidget(self.url_input)
        url_layout.addWidget(paste_btn)
        layout.addLayout(url_layout)

        # 选项设置
        options_layout = QHBoxLayout()

        # 质量选择
        quality_label = QLabel('🎯 质量选择:')
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(['自动选择', '最高质量', '中等质量', '最低质量'])
        self.quality_combo.setMinimumHeight(35)  # 增加下拉框高度

        # 保存路径
        path_label = QLabel('📂 保存路径:')
        self.path_input = QLineEdit()
        self.path_input.setText(self.settings.value('download_path', './downloads'))
        self.path_input.setMinimumHeight(35)  # 增加输入框高度

        browse_btn = QPushButton('选择目录...')
        browse_btn.clicked.connect(self.browse_output_path)
        browse_btn.setMinimumHeight(35)  # 增加按钮高度

        # 添加按钮
        add_btn = QPushButton('添加下载')
        add_btn.clicked.connect(self.add_download_task)
        add_btn.setStyleSheet('QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }')
        add_btn.setMinimumHeight(35)  # 增加按钮高度

        options_layout.addWidget(quality_label)
        options_layout.addWidget(self.quality_combo)
        options_layout.addWidget(path_label)
        options_layout.addWidget(self.path_input)
        options_layout.addWidget(browse_btn)
        options_layout.addStretch()
        options_layout.addWidget(add_btn)

        layout.addLayout(options_layout)

        return widget

    def create_task_list_section(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 标题
        title = QLabel('📊 下载任务列表')
        title.setFont(QFont('Microsoft YaHei', 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # 任务表格
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(6)
        self.task_table.setHorizontalHeaderLabels([
            '视频名称', '状态', '进度', '速度', '剩余时间', '操作'
        ])

        # 设置表格属性，允许用户手动调节列宽
        header = self.task_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # 视频名称可调节
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)  # 状态可调节
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)  # 进度可调节
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)  # 速度可调节
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)  # 剩余时间可调节
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)  # 操作可调节

        # 设置默认列宽
        self.task_table.setColumnWidth(0, 250)  # 视频名称
        self.task_table.setColumnWidth(1, 80)   # 状态
        self.task_table.setColumnWidth(2, 150)  # 进度
        self.task_table.setColumnWidth(3, 80)   # 速度
        self.task_table.setColumnWidth(4, 90)   # 剩余时间
        self.task_table.setColumnWidth(5, 120)  # 操作

        # 启用拖拽调节列宽
        header.setStretchLastSection(False)
        header.setCascadingSectionResizes(False)

        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        layout.addWidget(self.task_table)

        return widget

    def create_log_section(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 标题
        title = QLabel('📝 日志输出')
        title.setFont(QFont('Microsoft YaHei', 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setFont(QFont('Consolas', 9))
        layout.addWidget(self.log_text)

        # 清空按钮
        clear_btn = QPushButton('清空日志')
        clear_btn.clicked.connect(self.log_text.clear)
        layout.addWidget(clear_btn)

        return widget

    def create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # HTTP服务器状态
        self.server_status = QLabel('HTTP服务器: 待启动')
        self.status_bar.addWidget(self.server_status)

        # 下载统计
        self.download_stats = QLabel('下载统计: 今日0个 总计0个')
        self.status_bar.addPermanentWidget(self.download_stats)

    def setup_icon(self):
        """设置应用程序图标"""
        try:
            # 获取图标文件路径
            icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icon', 'app.ico')

            if os.path.exists(icon_path):
                # 设置窗口图标
                icon = QIcon(icon_path)
                self.setWindowIcon(icon)
                # 保存图标引用供系统托盘使用
                self.app_icon = icon
                print(f"成功加载应用图标: {icon_path}")
            else:
                print(f"图标文件不存在: {icon_path}")
                # 使用默认图标
                self.app_icon = self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon)
        except Exception as e:
            print(f"加载图标失败: {e}")
            # 使用默认图标
            self.app_icon = self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon)

    def create_system_tray(self):
        # 检查系统是否支持托盘
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        # 使用应用图标
        if hasattr(self, 'app_icon'):
            self.tray_icon.setIcon(self.app_icon)
        else:
            self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))

        # 托盘菜单
        tray_menu = QMenu()

        show_action = tray_menu.addAction('显示主窗口')
        show_action.triggered.connect(self.show)

        tray_menu.addSeparator()

        quit_action = tray_menu.addAction('退出')
        quit_action.triggered.connect(self.quit_application)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()

    # setup_worker方法已移除，使用全局任务管理器代替

    def setup_task_manager(self):
        """设置任务管理器回调"""
        # 启动任务管理器
        self.task_manager.start()

        # 注册事件回调
        self.task_manager.add_callback(TaskEvent.TASK_ADDED, self.on_task_added)
        self.task_manager.add_callback(TaskEvent.TASK_PROGRESS, self.on_task_progress_event)
        self.task_manager.add_callback(TaskEvent.TASK_COMPLETED, self.on_task_completed_event)
        self.task_manager.add_callback(TaskEvent.TASK_FAILED, self.on_task_failed_event)
        self.task_manager.add_callback(TaskEvent.LOG_MESSAGE, self.on_log_message_event)

        # 加载已有任务
        self.load_existing_tasks()

    def on_task_added(self, event_data: TaskEventData):
        """任务添加事件处理"""
        try:
            self.task_added_signal.emit(event_data)
        except Exception as e:
            print(f"GUI任务添加事件处理错误: {e}")

    def on_task_progress_event(self, event_data: TaskEventData):
        """任务进度事件处理"""
        try:
            self.task_progress_signal.emit(event_data)
        except Exception as e:
            print(f"GUI任务进度事件处理错误: {e}")

    def on_task_completed_event(self, event_data: TaskEventData):
        """任务完成事件处理"""
        try:
            self.task_completed_signal.emit(event_data)
        except Exception as e:
            print(f"GUI任务完成事件处理错误: {e}")

    def on_task_failed_event(self, event_data: TaskEventData):
        """任务失败事件处理"""
        try:
            self.task_failed_signal.emit(event_data)
        except Exception as e:
            print(f"GUI任务失败事件处理错误: {e}")

    def on_log_message_event(self, event_data: TaskEventData):
        """日志消息事件处理"""
        try:
            self.log_message_signal.emit(event_data)
        except Exception as e:
            print(f"GUI日志消息事件处理错误: {e}")

    # initialize_downloader方法已移除，使用全局任务管理器代替

    def paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text and ('m3u8' in text.lower() or 'http' in text.lower()):
            self.url_input.setText(text)

    def browse_output_path(self):
        path = QFileDialog.getExistingDirectory(self, '选择下载目录', self.path_input.text())
        if path:
            self.path_input.setText(path)

    def add_download_task(self):
        url = self.url_input.text().strip()
        if not url:
            self.log_message('❌ 请输入有效的URL')
            return

        if not url.startswith('http'):
            self.log_message('❌ URL格式不正确')
            return

        output_path = self.path_input.text().strip()
        if not output_path:
            output_path = './downloads'

        # 生成文件名
        filename = f"video_{int(time.time())}"

        try:
            self.log_message(f'正在添加下载任务: {url}')

            # 使用全局任务管理器（在后台线程中运行）
            import threading

            def add_task_thread():
                import asyncio
                async def add_task_async():
                    task_id = await self.task_manager.add_download_task(url, output_path, filename)
                    await self.task_manager.start_download(task_id)

                # 如果没有事件循环，创建一个新的
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                loop.run_until_complete(add_task_async())

            # 在新线程中执行异步任务
            task_thread = threading.Thread(target=add_task_thread, daemon=True)
            task_thread.start()

            self.url_input.clear()

        except Exception as e:
            self.log_message(f'添加任务失败: {str(e)}')

    def add_task_to_table(self, task_id: str, filename: str, url: str):
        row = self.task_table.rowCount()
        self.task_table.insertRow(row)

        # 存储任务信息
        self.tasks[task_id] = {
            'row': row,
            'filename': filename,
            'url': url,
            'status': '等待中'
        }

        # 设置表格内容
        self.task_table.setItem(row, 0, QTableWidgetItem(f'📹 {filename}'))
        self.task_table.setItem(row, 1, QTableWidgetItem('等待中'))

        # 进度条
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        self.task_table.setCellWidget(row, 2, progress_bar)

        self.task_table.setItem(row, 3, QTableWidgetItem('-'))
        self.task_table.setItem(row, 4, QTableWidgetItem('-'))

        # 操作按钮
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)

        start_btn = QPushButton('▶️')
        start_btn.setToolTip('开始下载')
        start_btn.clicked.connect(lambda: self.start_download(task_id))

        pause_btn = QPushButton('⏸️')
        pause_btn.setToolTip('暂停下载')
        pause_btn.clicked.connect(lambda: self.pause_download(task_id))

        btn_layout.addWidget(start_btn)
        btn_layout.addWidget(pause_btn)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        self.task_table.setCellWidget(row, 5, btn_widget)

    def start_download(self, task_id: str):
        import threading
        def start_task_thread():
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            async def start_async():
                await self.task_manager.start_download(task_id)

            loop.run_until_complete(start_async())

        task_thread = threading.Thread(target=start_task_thread, daemon=True)
        task_thread.start()
        self.log_message(f'🚀 开始下载: {self.tasks[task_id]["filename"]}')

    def pause_download(self, task_id: str):
        import threading
        def pause_task_thread():
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            async def pause_async():
                await self.task_manager.pause_download(task_id)

            loop.run_until_complete(pause_async())

        task_thread = threading.Thread(target=pause_task_thread, daemon=True)
        task_thread.start()
        self.log_message(f'⏸️ 暂停下载: {self.tasks[task_id]["filename"]}')

    def start_selected_downloads(self):
        selected_rows = set()
        for item in self.task_table.selectedItems():
            selected_rows.add(item.row())

        for task_id, task_info in self.tasks.items():
            if task_info['row'] in selected_rows:
                self.start_download(task_id)

    def pause_selected_downloads(self):
        selected_rows = set()
        for item in self.task_table.selectedItems():
            selected_rows.add(item.row())

        for task_id, task_info in self.tasks.items():
            if task_info['row'] in selected_rows:
                self.pause_download(task_id)

    def delete_selected_tasks(self):
        selected_rows = set()
        for item in self.task_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.information(self, '提示', '请先选中要删除的任务')
            return

        # 询问是否删除临时文件
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle('确认删除')
        msg_box.setText('确定要删除选中的任务吗？')
        msg_box.setInformativeText('是否同时删除临时文件？')

        delete_btn = msg_box.addButton('删除任务', QMessageBox.ButtonRole.AcceptRole)
        delete_with_files_btn = msg_box.addButton('删除任务和文件', QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = msg_box.addButton('取消', QMessageBox.ButtonRole.RejectRole)

        msg_box.exec()

        if msg_box.clickedButton() == cancel_btn:
            return

        delete_temp_files = (msg_box.clickedButton() == delete_with_files_btn)

        # 获取要删除的任务ID
        tasks_to_delete = []
        for task_id, task_info in self.tasks.items():
            if task_info['row'] in selected_rows:
                tasks_to_delete.append(task_id)

        # 异步删除任务
        import asyncio
        import threading

        def run_delete():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def delete_tasks():
                for task_id in tasks_to_delete:
                    await self.task_manager.delete_task(task_id, delete_temp_files)

            loop.run_until_complete(delete_tasks())
            loop.close()

        # 在单独线程中运行异步删除
        threading.Thread(target=run_delete, daemon=True).start()

        # 从GUI中移除任务
        for row in sorted(selected_rows, reverse=True):
            self.task_table.removeRow(row)

        # 更新任务字典
        for task_id in tasks_to_delete:
            if task_id in self.tasks:
                del self.tasks[task_id]

        self.log_message(f"已删除 {len(tasks_to_delete)} 个任务")

# 移除旧的Worker回调方法，现在使用任务管理器事件

    def log_message(self, message: str):
        timestamp = time.strftime('%H:%M:%S')
        formatted_message = f'[{timestamp}] {message}'
        self.log_text.append(formatted_message)

        # 自动滚动到底部
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)

    def show_settings(self):
        """显示设置对话框"""
        dialog = SettingsDialog(self)
        dialog.exec()

    def show_help(self):
        help_text = """
M3U8下载器使用帮助：

1. 在URL输入框中输入M3U8链接
2. 选择保存路径和视频质量
3. 点击"添加下载"按钮
4. 在任务列表中管理下载任务

快捷键：
- Enter: 添加下载任务
- Ctrl+V: 粘贴URL

支持功能：
- 多线程并发下载
- AES-128加密视频解密
- 自动合并为MP4格式
- 断点续传
- 下载速度限制
        """
        QMessageBox.information(self, '帮助', help_text)

    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.raise_()
                self.activateWindow()

    def closeEvent(self, event):
        """处理窗口关闭事件 - 默认最小化到托盘"""
        # 如果有系统托盘，默认最小化到托盘
        if self.tray_icon and self.tray_icon.isVisible():
            self.hide()
            event.ignore()
            # 显示提示信息（只显示一次）
            if not hasattr(self, '_tray_tip_shown'):
                self.tray_icon.showMessage(
                    'M3U8下载器',
                    '程序已最小化到系统托盘。\n双击托盘图标恢复窗口，右键托盘图标退出程序，或使用工具栏的退出按钮。',
                    QSystemTrayIcon.MessageIcon.Information,
                    5000
                )
                self._tray_tip_shown = True
        else:
            # 没有系统托盘支持，直接退出
            self.save_settings()
            event.accept()

    def _check_and_confirm_exit(self):
        """检查下载任务并确认是否退出"""
        downloading_tasks = []
        for task_id, task_info in self.tasks.items():
            if task_info.get('status') == 'downloading':
                downloading_tasks.append(task_info.get('filename', task_id))

        if downloading_tasks:
            reply = QMessageBox.warning(
                self,
                '确认退出',
                f'当前有 {len(downloading_tasks)} 个任务正在下载中：\n' +
                '\n'.join(downloading_tasks[:3]) +
                ('...' if len(downloading_tasks) > 3 else '') +
                '\n\n强制退出将中断这些下载，确定要退出吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            return reply == QMessageBox.StandardButton.Yes
        else:
            return True

    def quit_application(self):
        """从系统托盘退出应用程序"""
        if self._check_and_confirm_exit():
            # 设置强制退出标志，避免再次显示对话框
            self._force_quit = True
            # 关闭窗口，会触发closeEvent
            self.close()

    def force_exit_application(self):
        """工具栏退出按钮 - 强制退出应用程序"""
        try:
            # 保存设置
            self.save_settings()

            # 停止任务管理器
            if self.task_manager:
                self.task_manager.stop()

            # 强制退出应用程序
            import sys
            import os
            print("强制退出应用程序...")

            # 强制关闭所有窗口
            QApplication.quit()

            # 如果QApplication.quit()不起作用，使用sys.exit()
            sys.exit(0)

        except Exception as e:
            print(f"退出时发生错误: {e}")
            # 最后的手段，强制终止进程
            import os
            os._exit(0)

    def load_settings(self):
        # 恢复窗口位置和大小
        geometry = self.settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)

        # 恢复下载路径
        download_path = self.settings.value('download_path', './downloads')
        self.path_input.setText(download_path)

        # 恢复分割器状态
        splitter_state = self.settings.value('splitter_state')
        if splitter_state and hasattr(self, 'main_splitter'):
            self.main_splitter.restoreState(splitter_state)

        # 恢复表格列宽
        if hasattr(self, 'task_table'):
            for i in range(self.task_table.columnCount()):
                column_width = self.settings.value(f'column_width_{i}')
                if column_width:
                    self.task_table.setColumnWidth(i, int(column_width))

    def save_settings(self):
        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('download_path', self.path_input.text())

        # 保存分割器状态
        if hasattr(self, 'main_splitter'):
            self.settings.setValue('splitter_state', self.main_splitter.saveState())

        # 保存表格列宽
        if hasattr(self, 'task_table'):
            for i in range(self.task_table.columnCount()):
                self.settings.setValue(f'column_width_{i}', self.task_table.columnWidth(i))

    def update_server_status(self, status: str, port: int = None):
        """更新HTTP服务器状态显示"""
        if port:
            self.server_status.setText(f'HTTP服务器: {status} - 端口{port}')
        else:
            self.server_status.setText(f'HTTP服务器: {status}')

    def add_task_to_table_from_manager(self, event_data: TaskEventData):
        """从任务管理器添加任务到表格"""
        print(f"执行GUI任务添加: {event_data.task_id}")
        task_id = event_data.task_id
        data = event_data.data

        filename = data.get('filename', f'video_{task_id[:8]}')
        print(f"添加任务到表格: {filename}")
        self.add_task_to_table(task_id, filename, data.get('url', ''))
        print(f"任务已添加到GUI表格: {task_id}")

    def update_task_progress_from_manager(self, event_data: TaskEventData):
        """从任务管理器更新任务进度"""
        task_id = event_data.task_id
        progress_data = event_data.data

        if task_id in self.tasks:
            row = self.tasks[task_id]['row']

            # 更新状态
            status = progress_data.get('status', '未知')
            self.task_table.setItem(row, 1, QTableWidgetItem(status))

            # 更新进度条
            progress_bar = self.task_table.cellWidget(row, 2)
            if progress_bar and progress_data.get('total_segments', 0) > 0:
                percent = (progress_data.get('completed_segments', 0) / progress_data.get('total_segments', 1)) * 100
                progress_bar.setValue(int(percent))

            # 更新速度
            speed = progress_data.get('speed', 0)
            speed_text = f'{speed:.1f} KB/s' if speed > 0 else '-'
            self.task_table.setItem(row, 3, QTableWidgetItem(speed_text))

            # 更新剩余时间
            eta = progress_data.get('eta', 0)
            eta_text = f'{eta:.0f}s' if eta > 0 else '-'
            self.task_table.setItem(row, 4, QTableWidgetItem(eta_text))

    def update_task_completed_from_manager(self, event_data: TaskEventData):
        """从任务管理器更新任务完成状态"""
        task_id = event_data.task_id

        if task_id in self.tasks:
            row = self.tasks[task_id]['row']
            self.task_table.setItem(row, 1, QTableWidgetItem('已完成'))

            progress_bar = self.task_table.cellWidget(row, 2)
            if progress_bar:
                progress_bar.setValue(100)

    def update_task_failed_from_manager(self, event_data: TaskEventData):
        """从任务管理器更新任务失败状态"""
        task_id = event_data.task_id

        if task_id in self.tasks:
            row = self.tasks[task_id]['row']
            self.task_table.setItem(row, 1, QTableWidgetItem('失败'))

    def log_message_from_manager(self, event_data: TaskEventData):
        """从任务管理器接收日志消息"""
        data = event_data.data
        message = data.get('message', '')
        level = data.get('level', 'INFO')

        self.log_message(message)

    def load_existing_tasks(self):
        """加载已有任务到GUI"""
        try:
            all_tasks = self.task_manager.get_all_tasks()
            for task_id, task in all_tasks.items():
                self.add_task_to_table(task_id, task.filename, task.url)

                # 更新任务状态
                if task_id in self.tasks:
                    row = self.tasks[task_id]['row']
                    self.task_table.setItem(row, 1, QTableWidgetItem(task.progress.status))

                    # 更新进度条
                    progress_bar = self.task_table.cellWidget(row, 2)
                    if progress_bar and task.progress.total_segments > 0:
                        percent = (task.progress.completed_segments / task.progress.total_segments) * 100
                        progress_bar.setValue(int(percent))

        except Exception as e:
            self.log_message(f'加载已有任务失败: {str(e)}')

    def apply_theme(self):
        """应用主题样式"""
        try:
            config = get_config()
            theme = config.ui.theme

            if theme == "light":
                # Light主题样式
                light_style = """
                QMainWindow {
                    background-color: #ffffff;
                    color: #333333;
                }

                QWidget {
                    background-color: #ffffff;
                    color: #333333;
                }

                QLineEdit {
                    background-color: #ffffff;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 5px;
                    color: #333333;
                }

                QLineEdit:focus {
                    border: 2px solid #0078d4;
                }

                QPushButton {
                    background-color: #f0f0f0;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 6px 12px;
                    color: #333333;
                }

                QPushButton:hover {
                    background-color: #e6e6e6;
                    border: 1px solid #999999;
                }

                QPushButton:pressed {
                    background-color: #d9d9d9;
                }

                QComboBox {
                    background-color: #ffffff;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 5px;
                    color: #333333;
                }

                QComboBox:hover {
                    border: 1px solid #999999;
                }

                QComboBox::drop-down {
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 20px;
                    border-left-width: 1px;
                    border-left-color: #cccccc;
                    border-left-style: solid;
                    border-top-right-radius: 3px;
                    border-bottom-right-radius: 3px;
                }

                QTableWidget {
                    background-color: #ffffff;
                    alternate-background-color: #f8f8f8;
                    gridline-color: #e0e0e0;
                    color: #333333;
                    border: 1px solid #cccccc;
                }

                QTableWidget::item {
                    padding: 5px;
                    border-bottom: 1px solid #e0e0e0;
                }

                QTableWidget::item:selected {
                    background-color: #0078d4;
                    color: #ffffff;
                }

                QHeaderView::section {
                    background-color: #f0f0f0;
                    padding: 5px;
                    border: 1px solid #cccccc;
                    color: #333333;
                }

                QTextEdit {
                    background-color: #ffffff;
                    border: 1px solid #cccccc;
                    color: #333333;
                }

                QProgressBar {
                    border: 1px solid #cccccc;
                    border-radius: 3px;
                    text-align: center;
                    background-color: #f0f0f0;
                }

                QProgressBar::chunk {
                    background-color: #0078d4;
                    border-radius: 2px;
                }

                QStatusBar {
                    background-color: #f0f0f0;
                    border-top: 1px solid #cccccc;
                    color: #333333;
                }

                QMenuBar {
                    background-color: #f0f0f0;
                    color: #333333;
                    border-bottom: 1px solid #cccccc;
                }

                QMenuBar::item {
                    padding: 5px 10px;
                    background-color: transparent;
                }

                QMenuBar::item:selected {
                    background-color: #e6e6e6;
                }

                QMenu {
                    background-color: #ffffff;
                    border: 1px solid #cccccc;
                    color: #333333;
                }

                QMenu::item {
                    padding: 5px 20px;
                }

                QMenu::item:selected {
                    background-color: #0078d4;
                    color: #ffffff;
                }

                QToolBar {
                    background-color: #f0f0f0;
                    border: 1px solid #cccccc;
                    spacing: 3px;
                }

                QTabWidget::pane {
                    border: 1px solid #cccccc;
                    background-color: #ffffff;
                }

                QTabBar::tab {
                    background-color: #f0f0f0;
                    padding: 5px 10px;
                    margin-right: 2px;
                    border: 1px solid #cccccc;
                    border-bottom: none;
                }

                QTabBar::tab:selected {
                    background-color: #ffffff;
                    border-bottom: 1px solid #ffffff;
                }

                QGroupBox {
                    font-weight: bold;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    margin-top: 10px;
                    padding-top: 10px;
                }

                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                }
                """
                self.setStyleSheet(light_style)
            else:
                # 默认系统主题，清除自定义样式
                self.setStyleSheet("")

        except Exception as e:
            print(f"应用主题失败: {e}")


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关闭主窗口不退出程序

    window = M3U8DownloaderGUI()
    window.show()

    # 程序退出时保存设置
    app.aboutToQuit.connect(window.save_settings)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()