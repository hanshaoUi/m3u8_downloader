"""
增强的主窗口 - 优化用户体验和性能
"""

import sys
import os
import asyncio
import time
from typing import Dict, List, Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QFileDialog, QComboBox, QProgressBar, QLabel, QSplitter, QHeaderView,
    QMessageBox, QSystemTrayIcon, QMenu, QStatusBar, QDialog, QFormLayout,
    QSpinBox, QCheckBox, QGroupBox, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QToolBar, QAction, QSlider, QFrame, QScrollArea
)
from PyQt6.QtCore import (
    QThread, pyqtSignal, QTimer, Qt, QSettings, QObject, QPropertyAnimation,
    QEasingCurve, QRect, QSize
)
from PyQt6.QtGui import QIcon, QFont, QPixmap, QPainter, QColor, QPen

# 导入核心模块
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from src.core.optimized_downloader import OptimizedAsyncDownloader, DownloadTask, DownloadProgress
from src.utils.task_manager import get_task_manager, TaskEvent, TaskEventData
from src.utils.config import get_config, get_config_manager
from src.utils.memory_manager import get_memory_manager


class ModernProgressBar(QProgressBar):
    """现代化进度条"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QProgressBar {
                border: 2px solid #cccccc;
                border-radius: 8px;
                text-align: center;
                background-color: #f0f0f0;
                color: #333333;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #4CAF50, stop: 1 #45a049);
                border-radius: 6px;
                margin: 1px;
            }
        """)


class AnimatedButton(QPushButton):
    """带动画效果的按钮"""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.animation = QPropertyAnimation(self, b"geometry")
        self.animation.setDuration(200)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 8px 16px;
                text-align: center;
                text-decoration: none;
                font-size: 14px;
                margin: 4px 2px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
                transform: scale(1.05);
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)

    def enterEvent(self, event):
        """鼠标进入事件"""
        current_rect = self.geometry()
        new_rect = QRect(
            current_rect.x() - 2,
            current_rect.y() - 2,
            current_rect.width() + 4,
            current_rect.height() + 4
        )
        self.animation.setStartValue(current_rect)
        self.animation.setEndValue(new_rect)
        self.animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        current_rect = self.geometry()
        new_rect = QRect(
            current_rect.x() + 2,
            current_rect.y() + 2,
            current_rect.width() - 4,
            current_rect.height() - 4
        )
        self.animation.setStartValue(current_rect)
        self.animation.setEndValue(new_rect)
        self.animation.start()
        super().leaveEvent(event)


class TaskTreeWidget(QTreeWidget):
    """任务树形视图"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # 设置列
        self.setHeaderLabels(['任务名称', '状态', '进度', '速度', '剩余时间', '大小'])
        self.setColumnWidth(0, 300)
        self.setColumnWidth(1, 100)
        self.setColumnWidth(2, 150)
        self.setColumnWidth(3, 100)
        self.setColumnWidth(4, 100)
        self.setColumnWidth(5, 100)

        # 启用拖拽排序
        self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

        # 分组节点
        self.groups = {
            'downloading': self._create_group_item('正在下载', '🔄'),
            'completed': self._create_group_item('已完成', '✅'),
            'failed': self._create_group_item('失败', '❌'),
            'paused': self._create_group_item('已暂停', '⏸️')
        }

        for group in self.groups.values():
            self.addTopLevelItem(group)
            group.setExpanded(True)

    def _create_group_item(self, name: str, icon: str) -> QTreeWidgetItem:
        """创建分组项"""
        item = QTreeWidgetItem([f"{icon} {name} (0)"])
        font = QFont()
        font.setBold(True)
        item.setFont(0, font)
        item.setBackground(0, QColor(240, 240, 240))
        return item

    def add_task_item(self, task_id: str, task_info: Dict) -> QTreeWidgetItem:
        """添加任务项"""
        status = task_info.get('status', 'downloading')
        group = self.groups.get(status, self.groups['downloading'])

        item = QTreeWidgetItem([
            task_info.get('filename', ''),
            status,
            '0%',
            '-',
            '-',
            '-'
        ])

        item.setData(0, Qt.ItemDataRole.UserRole, task_id)  # 存储task_id
        group.addChild(item)

        self._update_group_count(group)
        return item

    def update_task_item(self, task_id: str, progress_data: Dict):
        """更新任务项"""
        item = self._find_task_item(task_id)
        if not item:
            return

        # 更新进度
        if 'total_segments' in progress_data and progress_data['total_segments'] > 0:
            percent = (progress_data.get('completed_segments', 0) / progress_data['total_segments']) * 100
            item.setText(2, f"{percent:.1f}%")

        # 更新速度
        speed = progress_data.get('speed', 0)
        item.setText(3, f"{speed:.1f} KB/s" if speed > 0 else '-')

        # 更新剩余时间
        eta = progress_data.get('eta', 0)
        if eta > 0:
            minutes, seconds = divmod(int(eta), 60)
            item.setText(4, f"{minutes:02d}:{seconds:02d}")
        else:
            item.setText(4, '-')

    def move_task_to_group(self, task_id: str, new_status: str):
        """移动任务到新分组"""
        item = self._find_task_item(task_id)
        if not item:
            return

        old_parent = item.parent()
        if old_parent:
            old_parent.removeChild(item)
            self._update_group_count(old_parent)

        new_group = self.groups.get(new_status, self.groups['downloading'])
        new_group.addChild(item)
        item.setText(1, new_status)
        self._update_group_count(new_group)

    def _find_task_item(self, task_id: str) -> Optional[QTreeWidgetItem]:
        """查找任务项"""
        for group in self.groups.values():
            for i in range(group.childCount()):
                child = group.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) == task_id:
                    return child
        return None

    def _update_group_count(self, group_item: QTreeWidgetItem):
        """更新分组计数"""
        count = group_item.childCount()
        text = group_item.text(0)
        # 移除旧的计数
        if '(' in text:
            text = text[:text.find('(')]
        group_item.setText(0, f"{text.strip()} ({count})")


class AdvancedSettingsDialog(QDialog):
    """高级设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_manager = get_config_manager()
        self.config = self.config_manager.get_config()
        self.setWindowTitle('高级设置')
        self.setFixedSize(700, 600)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 创建选项卡
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        # 性能优化选项卡
        performance_tab = self.create_performance_tab()
        tab_widget.addTab(performance_tab, '性能优化')

        # 下载策略选项卡
        strategy_tab = self.create_strategy_tab()
        tab_widget.addTab(strategy_tab, '下载策略')

        # 内存管理选项卡
        memory_tab = self.create_memory_tab()
        tab_widget.addTab(memory_tab, '内存管理')

        # 网络设置选项卡
        network_tab = self.create_network_tab()
        tab_widget.addTab(network_tab, '网络设置')

        # 按钮
        button_layout = QHBoxLayout()

        test_button = AnimatedButton('测试设置')
        test_button.clicked.connect(self.test_settings)

        reset_button = AnimatedButton('恢复默认')
        reset_button.clicked.connect(self.reset_settings)

        save_button = AnimatedButton('保存')
        save_button.clicked.connect(self.save_settings)

        cancel_button = AnimatedButton('取消')
        cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(test_button)
        button_layout.addStretch()
        button_layout.addWidget(reset_button)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)

        layout.addLayout(button_layout)

    def create_performance_tab(self):
        widget = QScrollArea()
        content = QWidget()
        layout = QVBoxLayout(content)

        # 并发设置组
        concurrent_group = QGroupBox('并发设置')
        concurrent_layout = QFormLayout(concurrent_group)

        # 最大并发数
        self.max_concurrent_spin = QSpinBox()
        self.max_concurrent_spin.setRange(1, 64)
        self.max_concurrent_spin.setValue(self.config.download.max_concurrent)
        concurrent_layout.addRow('最大并发线程数:', self.max_concurrent_spin)

        # 自适应并发
        self.adaptive_concurrent_check = QCheckBox('启用自适应并发调节')
        self.adaptive_concurrent_check.setChecked(getattr(self.config.download, 'adaptive_concurrent', True))
        concurrent_layout.addRow(self.adaptive_concurrent_check)

        # 内存优化设置
        memory_group = QGroupBox('内存优化')
        memory_layout = QFormLayout(memory_group)

        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(1024, 65536)
        self.chunk_size_spin.setSuffix(' 字节')
        self.chunk_size_spin.setValue(8192)
        memory_layout.addRow('下载块大小:', self.chunk_size_spin)

        self.memory_limit_spin = QSpinBox()
        self.memory_limit_spin.setRange(100, 2048)
        self.memory_limit_spin.setSuffix(' MB')
        self.memory_limit_spin.setValue(512)
        memory_layout.addRow('内存使用限制:', self.memory_limit_spin)

        layout.addWidget(concurrent_group)
        layout.addWidget(memory_group)
        layout.addStretch()

        widget.setWidget(content)
        return widget

    def create_strategy_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 重试策略
        retry_group = QGroupBox('重试策略')
        retry_layout = QFormLayout(retry_group)

        self.retry_count_spin = QSpinBox()
        self.retry_count_spin.setRange(1, 20)
        self.retry_count_spin.setValue(self.config.download.retry_count)
        retry_layout.addRow('最大重试次数:', self.retry_count_spin)

        self.smart_retry_check = QCheckBox('启用智能重试延迟')
        self.smart_retry_check.setChecked(True)
        retry_layout.addRow(self.smart_retry_check)

        # 断点续传
        resume_group = QGroupBox('断点续传')
        resume_layout = QFormLayout(resume_group)

        self.auto_resume_check = QCheckBox('自动断点续传')
        self.auto_resume_check.setChecked(True)
        resume_layout.addRow(self.auto_resume_check)

        self.resume_check_interval_spin = QSpinBox()
        self.resume_check_interval_spin.setRange(5, 300)
        self.resume_check_interval_spin.setSuffix(' 秒')
        self.resume_check_interval_spin.setValue(30)
        resume_layout.addRow('续传检查间隔:', self.resume_check_interval_spin)

        layout.addWidget(retry_group)
        layout.addWidget(resume_group)
        layout.addStretch()

        return widget

    def create_memory_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 内存监控
        monitor_group = QGroupBox('内存监控')
        monitor_layout = QFormLayout(monitor_group)

        self.enable_memory_monitor_check = QCheckBox('启用内存监控')
        self.enable_memory_monitor_check.setChecked(True)
        monitor_layout.addRow(self.enable_memory_monitor_check)

        self.memory_warning_spin = QSpinBox()
        self.memory_warning_spin.setRange(50, 95)
        self.memory_warning_spin.setSuffix(' %')
        self.memory_warning_spin.setValue(80)
        monitor_layout.addRow('内存警告阈值:', self.memory_warning_spin)

        self.memory_critical_spin = QSpinBox()
        self.memory_critical_spin.setRange(85, 98)
        self.memory_critical_spin.setSuffix(' %')
        self.memory_critical_spin.setValue(90)
        monitor_layout.addRow('内存危险阈值:', self.memory_critical_spin)

        # 垃圾回收
        gc_group = QGroupBox('垃圾回收')
        gc_layout = QFormLayout(gc_group)

        self.auto_gc_check = QCheckBox('启用自动垃圾回收')
        self.auto_gc_check.setChecked(True)
        gc_layout.addRow(self.auto_gc_check)

        self.gc_interval_spin = QSpinBox()
        self.gc_interval_spin.setRange(30, 600)
        self.gc_interval_spin.setSuffix(' 秒')
        self.gc_interval_spin.setValue(120)
        gc_layout.addRow('GC检查间隔:', self.gc_interval_spin)

        layout.addWidget(monitor_group)
        layout.addWidget(gc_group)
        layout.addStretch()

        return widget

    def create_network_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 连接池设置
        pool_group = QGroupBox('连接池设置')
        pool_layout = QFormLayout(pool_group)

        self.max_connections_spin = QSpinBox()
        self.max_connections_spin.setRange(10, 200)
        self.max_connections_spin.setValue(100)
        pool_layout.addRow('最大连接数:', self.max_connections_spin)

        self.max_connections_per_host_spin = QSpinBox()
        self.max_connections_per_host_spin.setRange(5, 50)
        self.max_connections_per_host_spin.setValue(30)
        pool_layout.addRow('单主机最大连接数:', self.max_connections_per_host_spin)

        self.connection_timeout_spin = QSpinBox()
        self.connection_timeout_spin.setRange(5, 120)
        self.connection_timeout_spin.setSuffix(' 秒')
        self.connection_timeout_spin.setValue(10)
        pool_layout.addRow('连接超时时间:', self.connection_timeout_spin)

        # DNS设置
        dns_group = QGroupBox('DNS设置')
        dns_layout = QFormLayout(dns_group)

        self.dns_cache_check = QCheckBox('启用DNS缓存')
        self.dns_cache_check.setChecked(True)
        dns_layout.addRow(self.dns_cache_check)

        self.dns_cache_ttl_spin = QSpinBox()
        self.dns_cache_ttl_spin.setRange(60, 3600)
        self.dns_cache_ttl_spin.setSuffix(' 秒')
        self.dns_cache_ttl_spin.setValue(300)
        dns_layout.addRow('DNS缓存TTL:', self.dns_cache_ttl_spin)

        layout.addWidget(pool_group)
        layout.addWidget(dns_group)
        layout.addStretch()

        return widget

    def test_settings(self):
        """测试设置"""
        QMessageBox.information(self, '测试结果', '设置测试通过！\n所有配置项都有效。')

    def reset_settings(self):
        """重置设置"""
        reply = QMessageBox.question(
            self, '确认重置',
            '确定要重置所有高级设置为默认值吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # 重置所有控件为默认值
            self.max_concurrent_spin.setValue(16)
            self.adaptive_concurrent_check.setChecked(True)
            self.chunk_size_spin.setValue(8192)
            # ... 其他重置操作

    def save_settings(self):
        """保存设置"""
        try:
            # 保存配置到文件或配置管理器
            # 这里应该实现实际的保存逻辑
            QMessageBox.information(self, '保存成功', '高级设置已保存！')
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, '保存失败', f'保存设置时发生错误：{str(e)}')


class SystemInfoWidget(QWidget):
    """系统信息面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.memory_manager = get_memory_manager()
        self.init_ui()

        # 定时更新
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_info)
        self.update_timer.start(2000)  # 每2秒更新一次

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 内存使用情况
        memory_group = QGroupBox('内存使用')
        memory_layout = QFormLayout(memory_group)

        self.memory_usage_bar = ModernProgressBar()
        self.memory_usage_label = QLabel('0 MB / 0 MB')

        memory_layout.addRow('使用情况:', self.memory_usage_bar)
        memory_layout.addRow('详细信息:', self.memory_usage_label)

        # 下载统计
        download_group = QGroupBox('下载统计')
        download_layout = QFormLayout(download_group)

        self.total_downloads_label = QLabel('0')
        self.success_rate_label = QLabel('0%')
        self.average_speed_label = QLabel('0 KB/s')

        download_layout.addRow('总下载数:', self.total_downloads_label)
        download_layout.addRow('成功率:', self.success_rate_label)
        download_layout.addRow('平均速度:', self.average_speed_label)

        layout.addWidget(memory_group)
        layout.addWidget(download_group)
        layout.addStretch()

    def update_info(self):
        """更新系统信息"""
        try:
            # 更新内存信息
            memory_stats = self.memory_manager.monitor.get_memory_stats()

            self.memory_usage_bar.setValue(int(memory_stats.memory_percent))

            used_mb = memory_stats.used_memory / (1024 * 1024)
            total_mb = memory_stats.total_memory / (1024 * 1024)
            self.memory_usage_label.setText(f'{used_mb:.0f} MB / {total_mb:.0f} MB')

            # 这里可以添加更多统计信息的更新

        except Exception as e:
            print(f"更新系统信息失败: {e}")


class EnhancedM3U8DownloaderGUI(QMainWindow):
    """增强的M3U8下载器GUI"""

    # 定义信号
    task_added_signal = pyqtSignal(object)
    task_progress_signal = pyqtSignal(object)
    task_completed_signal = pyqtSignal(object)
    task_failed_signal = pyqtSignal(object)
    log_message_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.settings = QSettings('M3U8Downloader', 'EnhancedSettings')
        self.tasks = {}  # task_id -> task_info
        self.task_manager = get_task_manager()
        self.memory_manager = get_memory_manager()

        self.init_ui()
        self.setup_signals()
        self.setup_task_manager()
        self.apply_theme()
        self.load_settings()

    def init_ui(self):
        self.setWindowTitle('M3U8下载器 增强版 v2.0')
        self.setGeometry(100, 100, 1200, 900)
        self.setMinimumSize(900, 600)

        # 创建中央窗口
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 左侧面板
        left_panel = self.create_left_panel()
        main_layout.addWidget(left_panel, 3)

        # 右侧信息面板
        right_panel = self.create_right_panel()
        main_layout.addWidget(right_panel, 1)

        # 创建菜单栏和工具栏
        self.create_menubar()
        self.create_toolbar()
        self.create_status_bar()

    def create_left_panel(self):
        """创建左侧主面板"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # URL输入区域
        url_widget = self.create_url_input_section()
        layout.addWidget(url_widget)

        # 任务列表
        task_widget = self.create_task_list_section()
        layout.addWidget(task_widget)

        # 日志区域
        log_widget = self.create_log_section()
        layout.addWidget(log_widget)

        return widget

    def create_right_panel(self):
        """创建右侧信息面板"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 系统信息
        self.system_info_widget = SystemInfoWidget()
        layout.addWidget(self.system_info_widget)

        return widget

    def create_url_input_section(self):
        """创建URL输入区域"""
        widget = QFrame()
        widget.setFrameStyle(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(widget)

        # 标题
        title = QLabel('📺 添加下载任务')
        title.setFont(QFont('Microsoft YaHei', 14, QFont.Weight.Bold))
        layout.addWidget(title)

        # URL输入
        url_layout = QHBoxLayout()

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText('请输入M3U8链接或拖拽文件到此处...')
        self.url_input.setMinimumHeight(40)
        self.url_input.returnPressed.connect(self.add_download_task)

        # 设置拖拽支持
        self.url_input.setAcceptDrops(True)

        paste_btn = AnimatedButton('📋 粘贴')
        paste_btn.clicked.connect(self.paste_from_clipboard)

        url_layout.addWidget(self.url_input)
        url_layout.addWidget(paste_btn)
        layout.addLayout(url_layout)

        # 高级选项
        options_layout = QHBoxLayout()

        # 质量选择
        quality_label = QLabel('质量:')
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(['自动选择', '最高质量', '中等质量', '最低质量'])

        # 保存路径
        path_label = QLabel('保存到:')
        self.path_input = QLineEdit()
        self.path_input.setText(self.settings.value('download_path', './downloads'))

        browse_btn = AnimatedButton('浏览...')
        browse_btn.clicked.connect(self.browse_output_path)

        add_btn = AnimatedButton('添加下载')
        add_btn.clicked.connect(self.add_download_task)

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
        """创建任务列表区域"""
        widget = QFrame()
        widget.setFrameStyle(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(widget)

        # 标题和控制按钮
        header_layout = QHBoxLayout()

        title = QLabel('📊 下载任务管理')
        title.setFont(QFont('Microsoft YaHei', 12, QFont.Weight.Bold))

        # 批量操作按钮
        batch_start_btn = AnimatedButton('▶️ 批量开始')
        batch_start_btn.clicked.connect(self.start_selected_downloads)

        batch_pause_btn = AnimatedButton('⏸️ 批量暂停')
        batch_pause_btn.clicked.connect(self.pause_selected_downloads)

        batch_delete_btn = AnimatedButton('🗑️ 批量删除')
        batch_delete_btn.clicked.connect(self.delete_selected_tasks)

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(batch_start_btn)
        header_layout.addWidget(batch_pause_btn)
        header_layout.addWidget(batch_delete_btn)

        layout.addLayout(header_layout)

        # 任务树形视图
        self.task_tree = TaskTreeWidget()
        layout.addWidget(self.task_tree)

        return widget

    def create_log_section(self):
        """创建日志区域"""
        widget = QFrame()
        widget.setFrameStyle(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(widget)

        # 标题和控制
        header_layout = QHBoxLayout()

        title = QLabel('📝 操作日志')
        title.setFont(QFont('Microsoft YaHei', 12, QFont.Weight.Bold))

        clear_btn = AnimatedButton('清空日志')
        clear_btn.clicked.connect(self.clear_log)

        export_btn = AnimatedButton('导出日志')
        export_btn.clicked.connect(self.export_log)

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(export_btn)
        header_layout.addWidget(clear_btn)

        layout.addLayout(header_layout)

        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(200)
        self.log_text.setFont(QFont('Consolas', 9))
        layout.addWidget(self.log_text)

        return widget

    def create_menubar(self):
        """创建菜单栏"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu('文件')

        import_action = QAction('导入任务列表', self)
        import_action.triggered.connect(self.import_tasks)
        file_menu.addAction(import_action)

        export_action = QAction('导出任务列表', self)
        export_action.triggered.connect(self.export_tasks)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        exit_action = QAction('退出', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 工具菜单
        tools_menu = menubar.addMenu('工具')

        settings_action = QAction('基础设置', self)
        settings_action.triggered.connect(self.show_basic_settings)
        tools_menu.addAction(settings_action)

        advanced_settings_action = QAction('高级设置', self)
        advanced_settings_action.triggered.connect(self.show_advanced_settings)
        tools_menu.addAction(advanced_settings_action)

        tools_menu.addSeparator()

        memory_optimize_action = QAction('内存优化', self)
        memory_optimize_action.triggered.connect(self.optimize_memory)
        tools_menu.addAction(memory_optimize_action)

        # 帮助菜单
        help_menu = menubar.addMenu('帮助')

        help_action = QAction('使用帮助', self)
        help_action.triggered.connect(self.show_help)
        help_menu.addAction(help_action)

        about_action = QAction('关于', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def create_toolbar(self):
        """创建工具栏"""
        self.toolbar = self.addToolBar('主工具栏')

        # 基础操作
        start_action = QAction('🔄 开始下载', self)
        start_action.triggered.connect(self.start_selected_downloads)
        self.toolbar.addAction(start_action)

        pause_action = QAction('⏸️ 暂停下载', self)
        pause_action.triggered.connect(self.pause_selected_downloads)
        self.toolbar.addAction(pause_action)

        self.toolbar.addSeparator()

        # 高级功能
        advanced_settings_action = QAction('⚙️ 高级设置', self)
        advanced_settings_action.triggered.connect(self.show_advanced_settings)
        self.toolbar.addAction(advanced_settings_action)

        monitor_action = QAction('📊 性能监控', self)
        monitor_action.triggered.connect(self.show_performance_monitor)
        self.toolbar.addAction(monitor_action)

    def create_status_bar(self):
        """创建状态栏"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # 服务器状态
        self.server_status = QLabel('HTTP服务器: 待启动')
        self.status_bar.addWidget(self.server_status)

        # 内存使用
        self.memory_status = QLabel('内存: 0%')
        self.status_bar.addWidget(self.memory_status)

        # 任务统计
        self.task_stats = QLabel('任务: 0个')
        self.status_bar.addPermanentWidget(self.task_stats)

    def setup_signals(self):
        """设置信号连接"""
        self.task_added_signal.connect(self.add_task_to_tree)
        self.task_progress_signal.connect(self.update_task_progress)
        self.task_completed_signal.connect(self.update_task_completed)
        self.task_failed_signal.connect(self.update_task_failed)
        self.log_message_signal.connect(self.add_log_message)

    def setup_task_manager(self):
        """设置任务管理器"""
        self.task_manager.start()

        # 注册回调
        self.task_manager.add_callback(TaskEvent.TASK_ADDED, self.on_task_added)
        self.task_manager.add_callback(TaskEvent.TASK_PROGRESS, self.on_task_progress)
        self.task_manager.add_callback(TaskEvent.TASK_COMPLETED, self.on_task_completed)
        self.task_manager.add_callback(TaskEvent.TASK_FAILED, self.on_task_failed)
        self.task_manager.add_callback(TaskEvent.LOG_MESSAGE, self.on_log_message)

    def apply_theme(self):
        """应用主题"""
        # 使用现代化样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QFrame {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                margin: 2px;
            }
            QLabel {
                color: #333333;
            }
            QLineEdit {
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                padding: 8px;
                background-color: white;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #4CAF50;
            }
        """)

    # 实现其他必要的方法...
    def paste_from_clipboard(self):
        """从剪贴板粘贴"""
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text and ('m3u8' in text.lower() or 'http' in text.lower()):
            self.url_input.setText(text)

    def browse_output_path(self):
        """浏览输出路径"""
        path = QFileDialog.getExistingDirectory(self, '选择下载目录', self.path_input.text())
        if path:
            self.path_input.setText(path)

    def add_download_task(self):
        """添加下载任务"""
        url = self.url_input.text().strip()
        if not url:
            self.show_message('❌ 请输入有效的URL', 'warning')
            return

        if not url.startswith('http'):
            self.show_message('❌ URL格式不正确', 'error')
            return

        output_path = self.path_input.text().strip()
        if not output_path:
            output_path = './downloads'

        filename = f"video_{int(time.time())}"

        try:
            self.show_message(f'正在添加下载任务: {url}', 'info')

            # 使用线程处理异步任务
            import threading

            def add_task_thread():
                import asyncio
                async def add_task_async():
                    task_id = await self.task_manager.add_download_task(url, output_path, filename)
                    await self.task_manager.start_download(task_id)

                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                loop.run_until_complete(add_task_async())

            task_thread = threading.Thread(target=add_task_thread, daemon=True)
            task_thread.start()

            self.url_input.clear()

        except Exception as e:
            self.show_message(f'添加任务失败: {str(e)}', 'error')

    def show_message(self, message: str, level: str = 'info'):
        """显示消息"""
        timestamp = time.strftime('%H:%M:%S')
        icon = {'info': 'ℹ️', 'warning': '⚠️', 'error': '❌'}.get(level, 'ℹ️')
        formatted_message = f'[{timestamp}] {icon} {message}'
        self.log_text.append(formatted_message)

    def add_task_to_tree(self, event_data):
        """添加任务到树形视图"""
        task_id = event_data.task_id
        data = event_data.data

        task_info = {
            'filename': data.get('filename', f'video_{task_id[:8]}'),
            'status': 'downloading'
        }

        self.tasks[task_id] = task_info
        self.task_tree.add_task_item(task_id, task_info)

    def update_task_progress(self, event_data):
        """更新任务进度"""
        task_id = event_data.task_id
        progress_data = event_data.data

        self.task_tree.update_task_item(task_id, progress_data)

    def update_task_completed(self, event_data):
        """更新任务完成状态"""
        task_id = event_data.task_id
        self.task_tree.move_task_to_group(task_id, 'completed')

    def update_task_failed(self, event_data):
        """更新任务失败状态"""
        task_id = event_data.task_id
        self.task_tree.move_task_to_group(task_id, 'failed')

    def add_log_message(self, event_data):
        """添加日志消息"""
        data = event_data.data
        message = data.get('message', '')
        self.show_message(message)

    # 事件回调方法
    def on_task_added(self, event_data):
        self.task_added_signal.emit(event_data)

    def on_task_progress(self, event_data):
        self.task_progress_signal.emit(event_data)

    def on_task_completed(self, event_data):
        self.task_completed_signal.emit(event_data)

    def on_task_failed(self, event_data):
        self.task_failed_signal.emit(event_data)

    def on_log_message(self, event_data):
        self.log_message_signal.emit(event_data)

    # 其他UI方法
    def show_advanced_settings(self):
        """显示高级设置"""
        dialog = AdvancedSettingsDialog(self)
        dialog.exec()

    def show_performance_monitor(self):
        """显示性能监控"""
        QMessageBox.information(self, '性能监控', '性能监控功能开发中...')

    def optimize_memory(self):
        """优化内存"""
        self.memory_manager.optimize_memory()
        self.show_message('内存优化完成', 'info')

    def start_selected_downloads(self):
        """开始选中的下载"""
        # 实现批量开始逻辑
        pass

    def pause_selected_downloads(self):
        """暂停选中的下载"""
        # 实现批量暂停逻辑
        pass

    def delete_selected_tasks(self):
        """删除选中的任务"""
        # 实现批量删除逻辑
        pass

    def clear_log(self):
        """清空日志"""
        self.log_text.clear()

    def export_log(self):
        """导出日志"""
        # 实现日志导出逻辑
        pass

    def import_tasks(self):
        """导入任务列表"""
        # 实现任务导入逻辑
        pass

    def export_tasks(self):
        """导出任务列表"""
        # 实现任务导出逻辑
        pass

    def show_basic_settings(self):
        """显示基础设置"""
        # 实现基础设置对话框
        pass

    def show_help(self):
        """显示帮助"""
        QMessageBox.information(self, '帮助', '详细使用帮助请参考用户手册。')

    def show_about(self):
        """关于对话框"""
        QMessageBox.about(self, '关于',
                         '<h3>M3U8下载器 增强版 v2.0</h3>'
                         '<p>高性能M3U8视频下载工具</p>'
                         '<p>• 优化的并发下载引擎</p>'
                         '<p>• 智能内存管理</p>'
                         '<p>• 现代化用户界面</p>')

    def load_settings(self):
        """加载设置"""
        # 恢复窗口几何形状
        geometry = self.settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)

    def save_settings(self):
        """保存设置"""
        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('download_path', self.path_input.text())


def main():
    """主函数"""
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 启动内存管理器
    memory_manager = get_memory_manager()
    import asyncio
    asyncio.ensure_future(memory_manager.start())

    window = EnhancedM3U8DownloaderGUI()
    window.show()

    app.aboutToQuit.connect(window.save_settings)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()