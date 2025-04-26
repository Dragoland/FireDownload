import os
import sys
import json
import time
import logging
import hashlib
import urllib.parse
import re
import webbrowser
import requests
import subprocess
from collections import deque
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Deque
from concurrent.futures import ThreadPoolExecutor
from packaging import version

import yt_dlp
from PyQt5. QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QProgressBar, QComboBox, QFileDialog, QMessageBox, QSystemTrayIcon,
    QMenu, QTabWidget, QTextEdit, QCheckBox, QSpinBox, QStyleFactory,
    QDateTimeEdit, QGroupBox, QFormLayout, QDialog, QDialogButtonBox,
    QAbstractItemView, QStyledItemDelegate, QStatusBar, QSizePolicy, QStackedWidget,
    QFrame, QScrollArea, QSizeGrip, QGraphicsOpacityEffect
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSettings, QUrl, QSize,
    QDateTime, QRect, QPoint, QPropertyAnimation, QEasingCurve,
    QObject, QEvent, QThreadPool, QRunnable, QByteArray, QMetaObject, 
    Q_ARG, QTranslator, QLocale, QLibraryInfo, pyqtSlot
)
from PyQt5.QtGui import (
    QIcon, QPalette, QColor, QDesktopServices, QFont, QPixmap,
    QPainter, QPen, QLinearGradient, QBrush, QMouseEvent, QImage, 
    QImageReader, QCursor, QFontDatabase
)

# ==================== CONSTANTS AND CONFIG ====================
class Config:
    APP_NAME = "FireDownload"
    VERSION = "5.0"
    HISTORY_FILE = "history.json"
    CONFIG_FILE = "config.ini"
    LOG_FILE = "debug.log"
    MAX_CONCURRENT_DOWNLOADS = 5
    ICON = "Logo.ico"
    THUMBNAIL_CACHE = "thumbnails"
    LANG_DIR = "lang"
    
    SUPPORTED_SITES = {
        'YouTube': ['youtube.com', 'youtu.be'],
        'TikTok': ['tiktok.com', 'vm.tiktok.com'],
        'Instagram': ['instagram.com'],
        'Twitter': ['twitter.com', 'x.com'],
        'Twitch': ['twitch.tv', 'clips.twitch.tv'],
        'Reddit': ['reddit.com'],
        'Dailymotion': ['dailymotion.com'],
        'SoundCloud': ['soundcloud.com', 'on.soundcloud.com'],
        'Vimeo': ['vimeo.com'],
        'Facebook': ['facebook.com'],
        'LinkedIn': ['linkedin.com'],
        'Rumble': ['rumble.com'],
        'Bilibili': ['bilibili.com'],
        'Odysee': ['odysee.com']
    }

    QUALITY_OPTIONS = ["Best", "4K", "1440p", "1080p", "720p", "480p", "360p"]
    AUDIO_FORMATS = ["mp3", "wav", "ogg", "flac", "m4a"]
    VIDEO_FORMATS = ["mp4", "mkv", "webm", "avi", "mov"]
    
    @staticmethod
    def setup_logging():
        try:
            # Si LOG_FILE tiene un directorio, crearlo
            log_dir = os.path.dirname(Config.LOG_FILE)
            if log_dir:  # Solo crear directorio si hay una ruta especificada
                os.makedirs(log_dir, exist_ok=True)
        
            logging.basicConfig(
                filename=Config.LOG_FILE if Config.LOG_FILE else None,
                level=logging.DEBUG,
                format='%(asctime)s - %(levelname)s - %(message)s',
                encoding='utf-8'
            )
        except Exception as e:
            print(f"No se pudo configurar el logging: {str(e)}")
            # Configuración básica sin archivo si falla
            logging.basicConfig(
                level=logging.DEBUG,
                format='%(asctime)s - %(levelname)s - %(message)s'
            )

# ==================== INTERNATIONALIZATION ====================
class Translator:
    def __init__(self):
        self.translator = QTranslator()
        self.current_lang = "en"
        self.load_languages()
        
    def load_languages(self):
        self.languages = {
            "en": "English",
            "es": "Español",
            "fr": "Français",
            "de": "Deutsch",
            "ja": "日本語",
            "zh": "中文"
        }
        
    def set_language(self, lang_code: str, app: QApplication):
        if lang_code in self.languages:
            lang_path = os.path.join(Config.LANG_DIR, f"firedownload_{lang_code}.qm")
            if os.path.exists(lang_path):
                if self.translator.load(lang_path):
                    app.installTranslator(self.translator)
                    self.current_lang = lang_code
                    return True
        return False

# ==================== DATA MODELS ====================
class DownloadItem:
    def __init__(self, url: str, options: dict):
        self.url = url
        self.options = options
        self.status = "queued"  # queued, downloading, paused, completed, error, cancelled
        self.progress = 0
        self.speed = "0 B/s"
        self.eta = "--:--"
        self.metadata = {}
        self.start_time = None
        self.end_time = None
        self.file_path = ""
        self.worker_id = None
        self.bytes_downloaded = 0
        self.total_bytes = 0
        self.pause_requested = False
        self.resume_requested = False

class ScheduleItem:
    def __init__(self, urls: List[str], scheduled_time: QDateTime, repeat: bool = False):
        self.urls = urls
        self.scheduled_time = scheduled_time
        self.repeat = repeat
        self.completed = False

# ==================== UTILITIES ====================
class Utils:
    @staticmethod
    def validate_url(url: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(url)
            if not parsed.scheme in ('http', 'https'):
                return False
                
            domain = parsed.netloc.lower()
            clean_domain = domain.replace("www.", "").replace("m.", "")
            
            for domains in Config.SUPPORTED_SITES.values():
                if any(d in clean_domain for d in domains):
                    return True
            return False
            
        except Exception as e:
            logging.error(f"URL validation error: {str(e)}")
            return False

    @staticmethod
    def format_speed(speed: float) -> str:
        units = ['B/s', 'KB/s', 'MB/s', 'GB/s']
        unit = 0
        while speed >= 1024 and unit < len(units)-1:
            speed /= 1024
            unit += 1
        return f"{speed:.2f} {units[unit]}"

    @staticmethod
    def format_size(bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024.0:
                return f"{bytes:.2f} {unit}"
            bytes /= 1024.0
        return f"{bytes:.2f} GB"

    @staticmethod
    def get_platform_name(url: str) -> str:
        try:
            parsed = urllib.parse.urlparse(url)
            domain = parsed.netloc.lower()
            clean_domain = domain.replace("www.", "").replace("m.", "")
            
            for name, domains in Config.SUPPORTED_SITES.items():
                if any(d in clean_domain for d in domains):
                    return name
            return "Generic"
        except:
            return "Generic"

    @staticmethod
    def resource_path(relative_path: str) -> str:
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    @staticmethod
    def check_ffmpeg() -> Tuple[bool, str]:
        """Check if FFmpeg is installed and return path"""
        try:
            # Try common paths
            paths = [
                'ffmpeg',
                '/usr/bin/ffmpeg',
                '/usr/local/bin/ffmpeg',
                'C:/ffmpeg/bin/ffmpeg.exe',
                os.path.join(os.path.dirname(sys.executable), 'ffmpeg.exe')
            ]
            
            for path in paths:
                try:
                    result = subprocess.run([path, '-version'], 
                                          check=True, 
                                          stdout=subprocess.PIPE, 
                                          stderr=subprocess.PIPE)
                    if 'ffmpeg version' in result.stdout.decode('utf-8'):
                        return True, path
                except:
                    continue
                    
            return False, ""
        except Exception as e:
            logging.error(f"FFmpeg check failed: {str(e)}")
            return False, ""

# ==================== ERROR HANDLER ====================
class ErrorHandler(QObject):
    error_occurred = pyqtSignal(str, str)  # context, message
    
    def __init__(self):
        super().__init__()
        
    @classmethod
    def handle(cls, error: Exception, context: str = ""):
        error_types = {
            requests.ConnectionError: "Connection error. Check your internet.",
            yt_dlp.DownloadError: "Video platform error. FFmpeg may be required.",
            OSError: "System error: Disk space issue.",
            RuntimeError: "Processing error.",
            ValueError: "Invalid input.",
            subprocess.SubprocessError: "FFmpeg not found or not working."
        }
        
        error_msg = error_types.get(type(error), f"Unexpected error: {str(error)}")
        
        handler = cls()
        handler.error_occurred.emit(context, error_msg)
        
        logging.error(f"{context}: {error_msg}")

# ==================== THEME SYSTEM ====================
class AppTheme:
    THEMES = {
        "dark": {
            "primary": "#2E7D32",
            "secondary": "#FF5722",
            "background": "#212121",
            "text": "#FFFFFF",
            "card": "#263238",
            "progress_bg": "#37474F",
            "input_bg": "#252525",
            "border": "#454545",
            "highlight": "#4CAF50",
            "danger": "#F44336",
            "warning": "#FFC107"
        },
        "light": {
            "primary": "#388E3C",
            "secondary": "#F4511E",
            "background": "#FAFAFA",
            "text": "#212121",
            "card": "#FFFFFF",
            "progress_bg": "#E0E0E0",
            "input_bg": "#FFFFFF",
            "border": "#CCCCCC",
            "highlight": "#4CAF50",
            "danger": "#F44336",
            "warning": "#FFC107"
        }
    }

    @staticmethod
    def apply_theme(widget: QWidget, theme_name: str):
        theme = AppTheme.THEMES[theme_name]
        
        # Modern AnyUI-like styling with FireDownload colors
        style = f"""
            /* Base styles */
            QWidget {{
                background-color: {theme['background']};
                color: {theme['text']};
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
                selection-background-color: {theme['primary']};
                selection-color: white;
            }}
            
            /* Main window */
            QMainWindow {{
                background-color: {theme['background']};
                border: 1px solid {theme['border']};
            }}
            
            /* Buttons - Modern flat style */
            QPushButton {{
                background-color: {theme['primary']};
                color: white;
                border-radius: 6px;
                padding: 8px 16px;
                border: none;
                min-width: 80px;
                font-weight: 500;
            }}
            
            QPushButton:hover {{
                background-color: {theme['highlight']};
            }}
            
            QPushButton:pressed {{
                background-color: {theme['secondary']};
            }}
            
            QPushButton:disabled {{
                background-color: #666666;
                color: #AAAAAA;
            }}
            
            /* Tool buttons */
            QPushButton[flat="true"] {{
                background-color: transparent;
                border: 1px solid transparent;
                padding: 5px;
                border-radius: 4px;
            }}
            
            QPushButton[flat="true"]:hover {{
                border-color: {theme['border']};
            }}
            
            /* Inputs - Modern style */
            QLineEdit, QTextEdit, QComboBox, QSpinBox {{
                background-color: {theme['input_bg']};
                border: 1px solid {theme['border']};
                border-radius: 4px;
                padding: 6px;
                min-height: 28px;
            }}
            
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left-width: 1px;
                border-left-color: {theme['border']};
                border-left-style: solid;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
            }}
            
            /* Progress bar - Modern style */
            QProgressBar {{
                border: 1px solid {theme['border']};
                border-radius: 4px;
                text-align: center;
                background: {theme['progress_bg']};
                height: 20px;
            }}
            
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {theme['primary']}, stop:1 {theme['secondary']});
                border-radius: 3px;
            }}
            
            /* Group boxes - Modern card style */
            QGroupBox {{
                border: 1px solid {theme['border']};
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 15px;
                background: {theme['card']};
            }}
            
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
                font-weight: bold;
            }}
            
            /* List widgets - Modern style */
            QListWidget {{
                border: 1px solid {theme['border']};
                border-radius: 6px;
                background-color: {theme['input_bg']};
                alternate-background-color: {theme['card']};
            }}
            
            QListWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {theme['border']};
            }}
            
            QListWidget::item:hover {{
                background-color: {theme['card']};
            }}
            
            QListWidget::item:selected {{
                background-color: {theme['primary']};
                color: white;
            }}
            
            /* Tabs - Modern style */
            QTabWidget::pane {{
                border: 1px solid {theme['border']};
                border-radius: 6px;
                margin-top: 5px;
                background: {theme['card']};
            }}
            
            QTabBar::tab {{
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                background: {theme['card']};
            }}
            
            QTabBar::tab:selected {{
                background: {theme['background']};
                border-bottom: 2px solid {theme['primary']};
            }}
            
            QTabBar::tab:hover {{
                background: {theme['input_bg']};
            }}
            
            /* Scroll bars - Modern style */
            QScrollBar:vertical {{
                border: none;
                background: {theme['card']};
                width: 10px;
                margin: 0px 0px 0px 0px;
            }}
            
            QScrollBar::handle:vertical {{
                background: {theme['primary']};
                min-height: 20px;
                border-radius: 5px;
            }}
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
                height: 0px;
                subcontrol-position: top;
                subcontrol-origin: margin;
            }}
            
            /* Custom widgets */
            DownloadCard {{
                background: {theme['card']};
                border-radius: 6px;
                padding: 10px;
                margin: 5px;
            }}
            
            /* Special buttons */
            .danger-button {{
                background-color: {theme['danger']};
            }}
            
            .warning-button {{
                background-color: {theme['warning']};
                color: {theme['text']};
            }}
        """
        widget.setStyleSheet(style)
        
        # Set palette for better color consistency
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(theme['background']))
        palette.setColor(QPalette.WindowText, QColor(theme['text']))
        palette.setColor(QPalette.Base, QColor(theme['input_bg']))
        palette.setColor(QPalette.AlternateBase, QColor(theme['card']))
        palette.setColor(QPalette.ToolTipBase, QColor(theme['primary']))
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, QColor(theme['text']))
        palette.setColor(QPalette.Button, QColor(theme['primary']))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Highlight, QColor(theme['primary']))
        palette.setColor(QPalette.HighlightedText, Qt.white)
        widget.setPalette(palette)

# ==================== CUSTOM UI COMPONENTS ====================
class AnimatedButton(QPushButton):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._init_animations()
        self.setCursor(QCursor(Qt.PointingHandCursor))
        
    def _init_animations(self):
        # Hover animation
        self.hover_anim = QPropertyAnimation(self, b"geometry")
        self.hover_anim.setDuration(150)
        self.hover_anim.setEasingCurve(QEasingCurve.OutQuad)
        
        # Click animation
        self.click_anim = QPropertyAnimation(self, b"geometry")
        self.click_anim.setDuration(100)
        self.click_anim.setEasingCurve(QEasingCurve.OutQuad)
        
    def enterEvent(self, event: QEvent):
        self.hover_anim.stop()
        self.hover_anim.setStartValue(self.geometry())
        self.hover_anim.setEndValue(QRect(
            self.x()-2, self.y()-2,
            self.width()+4, self.height()+4
        ))
        self.hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        self.hover_anim.stop()
        self.hover_anim.setStartValue(self.geometry())
        self.hover_anim.setEndValue(self.geometry().adjusted(2, 2, -2, -2))
        self.hover_anim.start()
        super().leaveEvent(event)
        
    def mousePressEvent(self, event: QMouseEvent):
        self.click_anim.stop()
        self.click_anim.setStartValue(self.geometry())
        self.click_anim.setEndValue(self.geometry().adjusted(1, 1, -1, -1))
        self.click_anim.start()
        super().mousePressEvent(event)
        
    def mouseReleaseEvent(self, event: QMouseEvent):
        self.click_anim.stop()
        self.click_anim.setStartValue(self.geometry())
        self.click_anim.setEndValue(self.geometry().adjusted(-1, -1, 1, 1))
        self.click_anim.start()
        super().mouseReleaseEvent(event)

class DownloadCard(QWidget):
    cancel_requested = pyqtSignal(str)
    pause_requested = pyqtSignal(str)
    resume_requested = pyqtSignal(str)
    
    def __init__(self, download_item: DownloadItem, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.download_item = download_item
        self._setup_ui()
        
    def _setup_ui(self):
        self.setObjectName("DownloadCard")
        self.setMinimumHeight(80)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # Platform icon
        self.icon = QLabel()
        platform = Utils.get_platform_name(self.download_item.url)
        icon_path = Utils.resource_path(f"assets/{platform}.png")
        if not os.path.exists(icon_path):
            icon_path = Utils.resource_path("assets/generic.png")
        self.icon.setPixmap(QPixmap(icon_path).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.icon.setFixedSize(48, 48)
        
        # Main content
        content_layout = QVBoxLayout()
        content_layout.setSpacing(5)
        
        # Title and status
        title_layout = QHBoxLayout()
        
        self.title_label = QLabel(self.download_item.metadata.get('title', 'Loading...'))
        self.title_label.setStyleSheet("font-weight: bold;")
        self.title_label.setWordWrap(True)
        
        self.status_label = QLabel(self.download_item.status.capitalize())
        self.status_label.setAlignment(Qt.AlignRight)
        
        title_layout.addWidget(self.title_label, 1)
        title_layout.addWidget(self.status_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(self.download_item.progress)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        
        # Info row
        info_layout = QHBoxLayout()
        
        self.speed_label = QLabel(self.download_item.speed)
        self.eta_label = QLabel(self.download_item.eta)
        self.size_label = QLabel(
            f"{Utils.format_size(self.download_item.bytes_downloaded)} / "
            f"{Utils.format_size(self.download_item.total_bytes)}"
            if self.download_item.total_bytes > 0 else ""
        )
        
        info_layout.addWidget(self.speed_label)
        info_layout.addWidget(self.eta_label)
        info_layout.addStretch()
        info_layout.addWidget(self.size_label)
        
        content_layout.addLayout(title_layout)
        content_layout.addWidget(self.progress_bar)
        content_layout.addLayout(info_layout)
        
        # Control buttons
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(5)
        
        self.pause_btn = AnimatedButton("⏸")
        self.pause_btn.setFixedSize(30, 30)
        self.pause_btn.setToolTip("Pause download")
        self.pause_btn.setProperty("class", "warning-button")
        self.pause_btn.clicked.connect(self._pause)
        
        self.cancel_btn = AnimatedButton("✖")
        self.cancel_btn.setFixedSize(30, 30)
        self.cancel_btn.setToolTip("Cancel download")
        self.cancel_btn.setProperty("class", "danger-button")
        self.cancel_btn.clicked.connect(self._cancel)
        
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch()
        
        layout.addWidget(self.icon)
        layout.addLayout(content_layout, 1)
        layout.addLayout(btn_layout)
        
        self._update_button_states()
        
    def update_progress(self, progress: float, speed: str, eta: str, 
                       bytes_downloaded: int, total_bytes: int):
        self.progress_bar.setValue(int(progress))
        self.speed_label.setText(speed)
        self.eta_label.setText(eta)
        self.size_label.setText(
            f"{Utils.format_size(bytes_downloaded)} / "
            f"{Utils.format_size(total_bytes)}"
            if total_bytes > 0 else ""
        )
        
    def update_status(self, status: str):
        self.download_item.status = status
        self.status_label.setText(status.capitalize())
        self._update_button_states()
        
    def _update_button_states(self):
        if self.download_item.status == "downloading":
            self.pause_btn.setText("⏸")
            self.pause_btn.setToolTip("Pause download")
        elif self.download_item.status == "paused":
            self.pause_btn.setText("▶")
            self.pause_btn.setToolTip("Resume download")
            
        self.pause_btn.setVisible(self.download_item.status in ["downloading", "paused"])
        self.cancel_btn.setVisible(self.download_item.status != "completed")
        
    def _pause(self):
        if self.download_item.status == "downloading":
            self.pause_requested.emit(self.download_item.url)
        elif self.download_item.status == "paused":
            self.resume_requested.emit(self.download_item.url)
            
    def _cancel(self):
        self.cancel_requested.emit(self.download_item.url)

# ==================== CORE FUNCTIONALITY ====================
class DownloadWorker(QRunnable):
    def __init__(self, download_item: DownloadItem, manager: 'DownloadManager'):
        super().__init__()
        self.download_item = download_item
        self.manager = manager
        self._is_cancelled = False
        self._is_paused = False
        self.last_bytes = 0
        self.start_time = time.time()
        self.ffmpeg_checked = False
        self.ffmpeg_available = False
        self.ffmpeg_path = ""
        
    def run(self):
        try:
            self.download_item.status = "downloading"
            self.download_item.start_time = datetime.now().isoformat()
        
            # Verificar FFmpeg si es necesario
            if not self.ffmpeg_checked and self._needs_ffmpeg():
                self.ffmpeg_available, self.ffmpeg_path = Utils.check_ffmpeg()
                self.ffmpeg_checked = True
            
                if not self.ffmpeg_available:
                    raise subprocess.SubprocessError("FFmpeg not found")
        
            ydl_opts = self._build_ydl_opts()
        
            # Intentar hasta 3 veces antes de dar por fallida la descarga
            max_attempts = 3
            attempt = 0
            success = False
        
            while attempt < max_attempts and not success and not self._is_cancelled:
                attempt += 1
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        # Obtener metadatos primero
                        info = ydl.extract_info(self.download_item.url, download=False)
                        self.download_item.metadata = self._extract_metadata(info)
                        self.download_item.total_bytes = info.get('filesize', info.get('filesize_approx', 0))
                        self.manager.metadata_received.emit(self.download_item)
                    
                        if self._is_cancelled:
                            return
                    
                        # Descargar con manejo de errores mejorado
                        ydl.download([self.download_item.url])
                    
                        # Verificar si el archivo se descargó completamente
                        temp_file = ydl.prepare_filename(info)
                        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                            success = True
                            self.download_item.status = "completed"
                            self.download_item.end_time = datetime.now().isoformat()
                            self.download_item.file_path = os.path.join(
                                self.download_item.options['path'],
                                self._get_filename(info)
                            )
                            self.manager.download_complete.emit(self.download_item)
                        
                            if self.download_item.options.get('verify', False):
                                self._verify_download(info)
                        else:
                            logging.warning(f"Attempt {attempt}: Downloaded file is empty or missing")
                        
                except Exception as e:
                    logging.error(f"Attempt {attempt} failed: {str(e)}")
                    if attempt == max_attempts:
                        raise  # Relanzar la excepción en el último intento
                    time.sleep(5 * attempt)  # Esperar progresivamente entre intentos
                
            if not success and not self._is_cancelled:
                raise RuntimeError(f"Failed after {max_attempts} attempts")
            
        except Exception as e:
            if not self._is_cancelled:
                self.download_item.status = "error"
                ErrorHandler.handle(e, f"Download failed: {self.download_item.url}")
                self.manager.download_error.emit(self.download_item)
        finally:
            self.manager.worker_finished.emit(self.download_item.url)
    
    def _needs_ffmpeg(self) -> bool:
        return (self.download_item.options.get('audio_only', False) or 
                'merge' in self.download_item.options.get('format', ''))
    
    def _build_ydl_opts(self) -> dict:
        opts = {
            'outtmpl': os.path.join(
                self.download_item.options['path'],
                self._get_filename_template()
            ),
            'progress_hooks': [self._update_progress],
            'format': self._get_best_format(),
            'retries': 20,  # Aumentamos los reintentos
            'fragment_retries': 20,  # Reintentos para fragmentos
            'skip_unavailable_fragments': False,  # Mejor no saltar fragmentos
            'extract_flat': False,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': False,  # Queremos ver los errores
            'socket_timeout': 60,  # Aumentamos el timeout
            'noplaylist': not self.download_item.options.get('playlist', False),
            'merge_output_format': 'mp4',
            'writethumbnail': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['all', '-live_chat'],
            'subtitlesformat': 'best',
            'convert-subs': 'srt',
            'buffersize': 1024 * 1024 * 16,  # Buffer más grande (16MB)
            'http_chunk_size': 10485760,  # Tamaño de chunk de 10MB
            'continuedl': True,  # Continuar descargas incompletas
            'noresizebuffer': True,  # No redimensionar el buffer
            'ratelimit': None,  # Sin límite de velocidad
            'throttledratelimit': None,
            'retry_sleep_functions': {
            'http': lambda n: 3 + 0.5 * n,  # Espera progresiva entre reintentos
            'fragment': lambda n: 3 + 0.5 * n,
            }
        }
    
        if self.download_item.options.get('proxy'):
            opts['proxy'] = self.download_item.options['proxy']
    
        if self._needs_ffmpeg() and self.ffmpeg_available:
            opts['ffmpeg_location'] = self.ffmpeg_path
        
        return opts
    
    def _extract_metadata(self, info: dict) -> dict:
        return {
            'title': info.get('title', 'Untitled'),
            'duration': info.get('duration', 0),
            'uploader': info.get('uploader', 'Unknown'),
            'thumbnail': info.get('thumbnail'),
            'resolution': info.get('resolution', 'N/A'),
            'view_count': info.get('view_count', 0),
            'upload_date': info.get('upload_date', ''),
            'description': info.get('description', '')
        }
    
    def _update_progress(self, d: dict):
        if d['status'] == 'downloading' and not self._is_cancelled:
            while self._is_paused and not self._is_cancelled:
                time.sleep(0.5)
            
            if self._is_cancelled:
                return
            
            current = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
        
            # Asegurarse de que total no sea 0 para evitar división por cero
            if total <= 0:
                total = 1
            
            # Calcular progreso (asegurarse de que esté entre 0 y 100)
            progress = min(100.0, max(0.0, (current / total) * 100))
            self.download_item.progress = progress
            self.download_item.bytes_downloaded = current
            self.download_item.total_bytes = total
        
            # Calcular velocidad
            elapsed = max(0.1, time.time() - self.start_time)  # Evitar división por cero
            speed = (current - self.last_bytes) / elapsed
            self.last_bytes = current
            self.download_item.speed = Utils.format_speed(speed)
            self.download_item.eta = d.get('_eta_str', '--:--')
        
            # Emitir actualización de progreso
            QMetaObject.invokeMethod(self.manager, "progress_updated", 
                                   Qt.QueuedConnection,
                                   Q_ARG(object, self.download_item))
    
    def _get_best_format(self) -> str:
        """Obtener el formato adecuado considerando la compatibilidad"""
        if self.download_item.options['audio_only']:
            return 'bestaudio/best'
    
        # Priorizar formatos compatibles
        quality = self.download_item.options['quality']
        quality_map = {
            'Best': 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]',
            '4K': 'bv*[height<=2160][ext=mp4]+ba[ext=m4a]/b[height<=2160][ext=mp4]',
            '1440p': 'bv*[height<=1440][ext=mp4]+ba[ext=m4a]/b[height<=1440][ext=mp4]',
            '1080p': 'bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]',
            '720p': 'bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]',
            '480p': 'bv*[height<=480][ext=mp4]+ba[ext=m4a]/b[height<=480][ext=mp4]',
            '360p': 'bv*[height<=360][ext=mp4]+ba[ext=m4a]/b[height<=360][ext=mp4]'
        }
        return quality_map.get(quality, 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]')
    
    def _get_postprocessors(self) -> list:
        postprocessors = []
    
        if self.download_item.options['audio_only']:
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': self.download_item.options.get('audio_format', 'mp3'),
                'preferredquality': '320'
            })
    
        if self.download_item.options.get('subtitles', False):
            postprocessors.append({
                'key': 'FFmpegSubtitlesConvertor',
                'format': 'srt'
            })
    
        return postprocessors
    
    def _get_filename_template(self) -> str:
        template = self.download_item.options.get('filename_template', '%(title)s [%(resolution)s].%(ext)s')
        if self.download_item.options['audio_only']:
            template = template.replace('[%(resolution)s]', '')
        return template
    
    def _get_filename(self, info: dict) -> str:
        ext = 'mp3' if self.download_item.options['audio_only'] else info.get('ext', 'mp4')
        title = info.get('title', 'video')
        resolution = info.get('resolution', 'N/A')
        
        if self.download_item.options['audio_only']:
            return f"{title}.{ext}"
        return f"{title} [{resolution}].{ext}"
    
    def _verify_download(self, info: dict):
        file_path = os.path.join(
            self.download_item.options['path'],
            self._get_filename(info)
        )
    
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Downloaded file not found at {file_path}")
    
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            raise ValueError("Downloaded file is empty")
    
        expected_size = info.get('filesize', info.get('filesize_approx', 0))
        if expected_size > 0 and abs(file_size - expected_size) > (0.1 * expected_size):
            logging.warning(f"File size mismatch: expected {expected_size}, got {file_size}")
    
        # Verificación básica de integridad para videos
        if not self.download_item.options['audio_only']:
            try:
                result = subprocess.run(
                    [self.ffmpeg_path if self.ffmpeg_available else 'ffmpeg', 
                    '-v', 'error', 
                    '-i', file_path, 
                    '-f', 'null', '-'],
                    stderr=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    check=False
                )
                if result.returncode != 0:
                    raise RuntimeError(f"FFmpeg validation failed: {result.stderr.decode()}")
            except Exception as e:
                logging.error(f"File validation error: {str(e)}")
                raise RuntimeError("Downloaded file is corrupted") from e
    
    def pause(self):
        self._is_paused = True
        self.download_item.status = "paused"
        QMetaObject.invokeMethod(self.manager, "download_paused", 
                               Qt.QueuedConnection,
                               Q_ARG(str, self.download_item.url))
    
    def resume(self):
        self._is_paused = False
        self.download_item.status = "downloading"
        QMetaObject.invokeMethod(self.manager, "download_resumed", 
                               Qt.QueuedConnection,
                               Q_ARG(str, self.download_item.url))
    
    def cancel(self):
        self._is_cancelled = True
        self.download_item.status = "cancelled"
        QMetaObject.invokeMethod(self.manager, "download_cancelled", 
                               Qt.QueuedConnection,
                               Q_ARG(str, self.download_item.url))

class DownloadManager(QObject):
    progress_updated = pyqtSignal(object)  # DownloadItem
    download_complete = pyqtSignal(object)  # DownloadItem
    download_error = pyqtSignal(object)     # DownloadItem
    download_paused = pyqtSignal(str)       # URL
    download_resumed = pyqtSignal(str)      # URL
    download_cancelled = pyqtSignal(str)    # URL
    queue_updated = pyqtSignal(int)         # queue size
    metadata_received = pyqtSignal(object)  # DownloadItem
    worker_finished = pyqtSignal(str)       # URL
    
    def __init__(self):
        super().__init__()
        self.download_queue = deque()
        self.active_downloads = {}  # url: worker
        self.paused_downloads = {}  # url: worker
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(Config.MAX_CONCURRENT_DOWNLOADS)
        self.settings = QSettings(Config.CONFIG_FILE, QSettings.IniFormat)
        self.load_settings()
        self.window = None
        
    def set_window(self, window):
        self.window = window
        
    def load_settings(self):
        self.max_concurrent = int(self.settings.value("max_concurrent", Config.MAX_CONCURRENT_DOWNLOADS))
        self.thread_pool.setMaxThreadCount(self.max_concurrent)
    
    def add_download(self, urls: List[str], options: dict):
        valid_urls = [url for url in urls if Utils.validate_url(url)]
        
        for url in valid_urls:
            download_item = DownloadItem(url, options)
            self.download_queue.append(download_item)
            
            if self.window:
                card = DownloadCard(download_item)
                item = QListWidgetItem()
                item.setSizeHint(card.sizeHint())
                self.window.download_list.addItem(item)
                self.window.download_list.setItemWidget(item, card)
                
                # Connect card signals
                card.cancel_requested.connect(self.cancel_download)
                card.pause_requested.connect(self.pause_download)
                card.resume_requested.connect(self.resume_download)
        
        self.start_next_download()
        self.queue_updated.emit(len(self.download_queue))
    
    def start_next_download(self):
        while (len(self.active_downloads) < self.thread_pool.maxThreadCount() and 
               self.download_queue):
            download_item = self.download_queue.popleft()
            worker = DownloadWorker(download_item, self)
            self.active_downloads[download_item.url] = worker
            self.thread_pool.start(worker)
            self.queue_updated.emit(len(self.download_queue))
    
    def pause_download(self, url: str):
        if url in self.active_downloads:
            worker = self.active_downloads[url]
            worker.pause()
            self.paused_downloads[url] = worker
            del self.active_downloads[url]
            self.start_next_download()
    
    def resume_download(self, url: str):
        if url in self.paused_downloads:
            worker = self.paused_downloads[url]
            worker.resume()
            self.active_downloads[url] = worker
            del self.paused_downloads[url]
            
            # Ensure we don't exceed max concurrent downloads
            if len(self.active_downloads) > self.thread_pool.maxThreadCount():
                self.pause_download(next(iter(self.active_downloads.keys())))
    
    def cancel_download(self, url: str):
        # Cancel active download
        if url in self.active_downloads:
            self.active_downloads[url].cancel()
            del self.active_downloads[url]
            self.start_next_download()
        elif url in self.paused_downloads:
            self.paused_downloads[url].cancel()
            del self.paused_downloads[url]
        
        # Remove from queue
        self.download_queue = deque(item for item in self.download_queue if item.url != url)
        self.queue_updated.emit(len(self.download_queue))
        
        # Remove from UI if window is available
        if self.window:
            for i in range(self.window.download_list.count()):
                item = self.window.download_list.item(i)
                widget = self.window.download_list.itemWidget(item)
                if widget and widget.download_item.url == url:
                    self.window.download_list.takeItem(i)
                    break
    
    def get_download_status(self, url: str) -> Optional[str]:
        if url in self.active_downloads:
            return self.active_downloads[url].download_item.status
        elif url in self.paused_downloads:
            return self.paused_downloads[url].download_item.status
        
        for item in self.download_queue:
            if item.url == url:
                return "queued"
        
        return None
    
# ==================== SEARCH METHODS ====================
    def perform_search(self):
        """Perform a video search on the selected platform"""
        try:
            query = self.search_input.text().strip()
            if not query:
                self.show_error("Error", "Please enter search terms")
                return

            # Show loading state
            self.search_loading.setText("Searching... Please wait")
            self.search_stack.setCurrentIndex(0)
            self.search_btn.setEnabled(False)

            # Get selected platform
            platform = self.platform_combo.currentText().lower()

            # Run search in background thread
            worker = SearchWorker(query, platform)
            worker.signals.finished.connect(self.on_search_finished)
            worker.signals.error.connect(self.on_search_error)
            worker.signals.result.connect(self.on_search_result)
            QThreadPool.globalInstance().start(worker)

        except Exception as e:
            self.show_error("Search Error", f"Failed to start search: {str(e)}")
            logging.error(f"Search initialization error: {str(e)}")

    def on_search_result(self, results):
        """Handle successful search results"""
        try:
            self.search_results.clear()
        
            if not results:
                self.search_loading.setText("No results found")
                return
            
            self.search_stack.setCurrentIndex(1)
        
            for result in results:
                item = QListWidgetItem(result.get('title', 'Untitled'))
                item.setData(Qt.UserRole, result.get('url'))
                item.setToolTip(
                    f"Duration: {result.get('duration', 'N/A')}\n"
                    f"Views: {result.get('view_count', 'N/A')}\n"
                    f"Uploader: {result.get('uploader', 'N/A')}"
            )   
            
                # Load thumbnail async
                thumbnail = result.get('thumbnail')
                if thumbnail:
                    self.load_search_thumbnail(thumbnail, item)
                
                self.search_results.addItem(item)

        except Exception as e:
            self.show_error("Result Error", f"Failed to process results: {str(e)}")
            logging.error(f"Result processing error: {str(e)}")

    def on_search_finished(self):
        """Clean up after search completes"""
        self.search_btn.setEnabled(True)
        if self.search_results.count() == 0:
            self.search_loading.setText("No results found")
            self.search_stack.setCurrentIndex(0)

    def on_search_error(self, error_msg):
        """Handle search errors"""
        self.show_error("Search Error", error_msg)
        self.search_loading.setText("Search failed")
        self.search_btn.setEnabled(True)

    def load_search_thumbnail(self, url: str, item: QListWidgetItem):
        """Load and cache thumbnails for search results"""
        try:
            thumbnail_hash = hashlib.md5(url.encode()).hexdigest()
            cache_path = os.path.join(Config.THUMBNAIL_CACHE, f"{thumbnail_hash}.jpg")
        
            def download_thumbnail():
                try:
                    if os.path.exists(cache_path):
                        image = QImage(cache_path)
                    else:
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            image = QImage()
                            image.loadFromData(response.content)
                            image.save(cache_path, "JPEG")
                
                    # Update UI if item still exists
                    if self.search_results.row(item) >= 0:
                        pixmap = QPixmap.fromImage(image).scaled(
                            120, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                        item.setIcon(QIcon(pixmap))
                    
                except Exception as e:
                    logging.error(f"Thumbnail download failed: {str(e)}")

            QThreadPool.globalInstance().start(download_thumbnail)
        except Exception as e:
            logging.error(f"Thumbnail loading failed: {str(e)}")

# ==================== SEARCH WORKER ====================
class SearchSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    result = pyqtSignal(list)

class SearchWorker(QRunnable):
    def __init__(self, query, platform):
        super().__init__()
        self.query = query
        self.platform = platform
        self.signals = SearchSignals()

    def run(self):
        try:
            ydl_opts = {
                'extract_flat': True,
                'quiet': True,
                'default_search': 'ytsearch10:',
                'source_address': '0.0.0.0'
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                results = ydl.extract_info(self.query, download=False)
                if not results or 'entries' not in results:
                    self.signals.result.emit([])
                    return
                    
                processed_results = []
                for entry in results['entries']:
                    if not entry:
                        continue
                    processed_results.append({
                        'title': entry.get('title', 'Untitled'),
                        'url': entry.get('url'),
                        'thumbnail': entry.get('thumbnail'),
                        'duration': entry.get('duration'),
                        'view_count': entry.get('view_count'),
                        'uploader': entry.get('uploader')
                    })
                
                self.signals.result.emit(processed_results)
                
        except Exception as e:
            self.signals.error.emit(f"Search failed: {str(e)}")
            logging.error(f"Search error: {str(e)}")
        finally:
            self.signals.finished.emit()

# ==================== MAIN WINDOW ====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._init_config()
        self._init_ui()
        self._init_download_manager()
        self._init_connections()
        self._init_tray()
        self._check_ffmpeg()
        
    def _init_config(self):
        Config.setup_logging()
        self.settings = QSettings(Config.CONFIG_FILE, QSettings.IniFormat)
        self.dark_mode = self.settings.value("dark_mode", True, type=bool)
        self.current_path = self.settings.value("download_path", os.path.expanduser("~/Downloads"))
        self.current_language = self.settings.value("language", "en")
        
        # Create necessary directories
        os.makedirs(Config.THUMBNAIL_CACHE, exist_ok=True)
        os.makedirs(Config.LANG_DIR, exist_ok=True)
    
    def _check_ffmpeg(self):
        ffmpeg_available, ffmpeg_path = Utils.check_ffmpeg()
        if not ffmpeg_available:
            reply = QMessageBox.question(
                self,
                "FFmpeg Not Found",
                "FFmpeg is required for audio extraction and format merging. "
                "Would you like to download it now?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                webbrowser.open("https://ffmpeg.org/download.html")
    
    def _init_ui(self):
        self.setWindowTitle(f"{Config.APP_NAME} {Config.VERSION}")
        self.setMinimumSize(800, 600)
        self.setWindowIcon(QIcon(Utils.resource_path(Config.ICON)))

        # Contenedor principal con área de desplazamiento
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        # Main container with shadow effect
        main_container = QWidget()
        main_container.setObjectName("MainContainer")
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Header
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.logo = QLabel()
        self.logo.setPixmap(QPixmap(Utils.resource_path(Config.ICON)).scaled(48, 48))
        
        self.title = QLabel(Config.APP_NAME)
        self.title.setStyleSheet("font-size: 24px; font-weight: bold;")
        
        header_layout.addWidget(self.logo)
        header_layout.addWidget(self.title)
        header_layout.addStretch()
        
        # Main tabs
        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.addTab(self._create_download_tab(), "Downloads")
        self.tabs.addTab(self._create_history_tab(), "History")
        self.tabs.addTab(self._create_settings_tab(), "Settings")
        self.tabs.addTab(self._create_search_tab(), "Search")
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Assemble main layout
        main_layout.addWidget(header)
        main_layout.addWidget(self.tabs)
        
        self.setCentralWidget(main_container)
        
        # Apply theme
        AppTheme.apply_theme(self, "dark" if self.dark_mode else "light")
        
        # Restore window state
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        if self.settings.value("windowState"):
            self.restoreState(self.settings.value("windowState"))
    
    def _init_download_manager(self):
        self.download_manager = DownloadManager()
        self.download_manager.set_window(self)
        
        # Schedule timer
        self.schedule_timer = QTimer()
        self.schedule_timer.timeout.connect(self.check_scheduled_downloads)
        self.schedule_timer.start(60000)  # Check every minute
    
    def _init_connections(self):
        # Download Manager signals
        self.download_manager.progress_updated.connect(self.update_download_progress)
        self.download_manager.download_complete.connect(self.on_download_complete)
        self.download_manager.download_error.connect(self.on_download_error)
        self.download_manager.download_paused.connect(self.on_download_paused)
        self.download_manager.download_resumed.connect(self.on_download_resumed)
        self.download_manager.download_cancelled.connect(self.on_download_cancelled)
        self.download_manager.queue_updated.connect(self.update_queue_status)
        self.download_manager.metadata_received.connect(self.update_preview)
        self.download_manager.worker_finished.connect(self.on_worker_finished)
        
        # UI signals
        self.add_btn.clicked.connect(self.start_download)
        self.path_btn.clicked.connect(self.select_download_path)
        self.toggle_theme_btn.clicked.connect(self.toggle_theme)
        self.audio_check.toggled.connect(self.update_audio_ui)
        self.donation_btn.clicked.connect(self.open_donation)
        self.info_btn.clicked.connect(self.show_about)
        
        # History signals
        self.history_filter.textChanged.connect(self.filter_history)
        self.clear_history_btn.clicked.connect(self.clear_history)
        self.history_list.customContextMenuRequested.connect(self.show_history_context_menu)
        
        # Scheduling signals
        self.add_schedule_btn.clicked.connect(self.add_schedule)
        self.remove_schedule_btn.clicked.connect(self.remove_schedule)
        
        # Search signals
        self.search_btn.clicked.connect(self.perform_search)
        self.search_input.returnPressed.connect(self.perform_search)
        self.search_results.itemDoubleClicked.connect(self.add_search_result_to_downloads)
        
        # Language change
        self.language_combo.currentTextChanged.connect(self.change_language)
        
        # Load settings
        self.load_settings()
    
    def _init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(Utils.resource_path(Config.ICON)))
        
        menu = QMenu()
        open_action = menu.addAction("Open")
        open_action.triggered.connect(self.show)
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(QApplication.quit)
        
        self.tray.setContextMenu(menu)
        self.tray.show()
        self.tray.activated.connect(self.tray_activated)
    
# ==================== UI CREATION METHODS ====================
    def _create_download_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
    
        # URL Input Section
        url_group = QGroupBox("Enter URLs")
        url_layout = QVBoxLayout(url_group)
    
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("Paste one or more URLs (one per line)...")
        self.url_input.setAcceptRichText(False)
        self.url_input.setMinimumHeight(100)
    
        url_layout.addWidget(self.url_input)
    
        # Preview Section
        self.preview_group = QGroupBox("Preview")
        self.preview_group.setVisible(False)  # Hidden until metadata is loaded
        preview_layout = QHBoxLayout(self.preview_group)
    
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(200, 200)
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setText("No preview available")
    
        self.metadata_text = QTextEdit()
        self.metadata_text.setReadOnly(True)
    
        preview_layout.addWidget(self.thumbnail_label)
        preview_layout.addWidget(self.metadata_text, 1)
    
        # Download Options Section
        self.options_group = QGroupBox("Download Options")
        options_layout = QFormLayout(self.options_group)  # <-- Aquí se define options_layout
        options_layout.setVerticalSpacing(10)
    
        # Quality selection
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(Config.QUALITY_OPTIONS)
    
        # Audio options
        self.audio_check = QCheckBox("Audio Only")
        self.audio_format_combo = QComboBox()
        self.audio_format_combo.addItems(Config.AUDIO_FORMATS)
        self.audio_format_combo.setCurrentText("mp3")
    
        # Video format
        self.video_format_combo = QComboBox()
        self.video_format_combo.addItems(Config.VIDEO_FORMATS)
        self.video_format_combo.setCurrentText("mp4")
    
        # Subtitles option (AÑADIDO DESPUÉS DE DEFINIR options_layout)
        self.subs_check = QCheckBox("Download subtitles")
        self.subs_check.setChecked(True)
    
        # Destination path
        path_layout = QHBoxLayout()
        self.path_btn = AnimatedButton("📂")
        self.path_btn.setToolTip("Select download folder")
        self.path_btn.setFixedSize(30, 30)
        self.path_label = QLabel(self.current_path)
        self.path_label.setWordWrap(True)
        path_layout.addWidget(self.path_btn)
        path_layout.addWidget(self.path_label, 1)
    
        # Añadir filas al formulario (AHORA INCLUYENDO SUBTÍTULOS)
        options_layout.addRow("Quality:", self.quality_combo)
        options_layout.addRow(self.audio_check)
        options_layout.addRow("Audio Format:", self.audio_format_combo)
        options_layout.addRow("Video Format:", self.video_format_combo)
        options_layout.addRow(self.subs_check)  # <-- Añadido aquí
        options_layout.addRow("Destination:", path_layout)
        
        # Advanced Options Section
        self.advanced_group = QGroupBox("Advanced Options")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        advanced_layout = QFormLayout(self.advanced_group)
        
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("http://user:pass@host:port")
        
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(1, 10)
        
        self.verify_check = QCheckBox("Verify download integrity")
        self.playlist_check = QCheckBox("Download playlists")
        
        advanced_layout.addRow("Proxy:", self.proxy_input)
        advanced_layout.addRow("Retries:", self.retries_spin)
        advanced_layout.addRow(self.verify_check)
        advanced_layout.addRow(self.playlist_check)
        
        # Download List Section
        self.download_list = QListWidget()
        self.download_list.setAlternatingRowColors(True)
        self.download_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.download_list.setSpacing(5)
        
        # Control Buttons
        control_layout = QHBoxLayout()
        
        self.toggle_theme_btn = AnimatedButton("🌙" if self.dark_mode else "☀️")
        self.toggle_theme_btn.setFixedSize(30, 30)
        self.toggle_theme_btn.setToolTip("Toggle theme")
        
        self.donation_btn = AnimatedButton("❤ Donate")
        self.info_btn = AnimatedButton("ℹ About")
        self.add_btn = AnimatedButton("Add Download")
        self.add_btn.setIcon(QIcon.fromTheme("list-add"))
        
        control_layout.addWidget(self.toggle_theme_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.donation_btn)
        control_layout.addWidget(self.info_btn)
        control_layout.addWidget(self.add_btn)
        
        # Assemble layout
        layout.addWidget(url_group)
        layout.addWidget(self.preview_group)
        layout.addWidget(self.options_group)
        layout.addWidget(self.advanced_group)
        layout.addWidget(self.download_list, 1)
        layout.addLayout(control_layout)
        
        return tab

    def _create_history_tab(self) -> QWidget:
        """Create the history tab with search and filtering"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # Filter Section
        filter_group = QGroupBox("Filter History")
        filter_layout = QHBoxLayout(filter_group)
        
        self.history_filter = QLineEdit()
        self.history_filter.setPlaceholderText("Filter by title, URL or date...")
        self.history_filter.setClearButtonEnabled(True)
        
        self.clear_history_btn = AnimatedButton("Clear History")
        
        filter_layout.addWidget(self.history_filter, 1)
        filter_layout.addWidget(self.clear_history_btn)
        
        # History List
        self.history_list = QListWidget()
        self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_list.setAlternatingRowColors(True)
        self.history_list.setSpacing(3)
        
        # Load history data
        self.load_history()
        
        layout.addWidget(filter_group)
        layout.addWidget(self.history_list, 1)
        
        return tab

    def _create_settings_tab(self) -> QWidget:
        """Create the settings tab with scheduling options"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # Scheduling Section
        self.scheduling_group = QGroupBox("Download Scheduling")
        scheduling_layout = QFormLayout(self.scheduling_group)
        
        self.schedule_datetime = QDateTimeEdit()
        self.schedule_datetime.setDateTime(QDateTime.currentDateTime())
        self.schedule_datetime.setCalendarPopup(True)
        
        self.schedule_repeat = QCheckBox("Repeat daily")
        self.schedule_list = QListWidget()
        self.schedule_list.setAlternatingRowColors(True)
        
        btn_layout = QHBoxLayout()
        self.add_schedule_btn = AnimatedButton("Add Schedule")
        self.remove_schedule_btn = AnimatedButton("Remove Selected")
        self.remove_schedule_btn.setEnabled(False)
        
        btn_layout.addWidget(self.add_schedule_btn)
        btn_layout.addWidget(self.remove_schedule_btn)
        
        scheduling_layout.addRow("Date & Time:", self.schedule_datetime)
        scheduling_layout.addRow(self.schedule_repeat)
        scheduling_layout.addRow(QLabel("Scheduled Downloads:"))
        scheduling_layout.addRow(self.schedule_list)
        scheduling_layout.addRow(btn_layout)
        
        # Language Section
        self.language_group = QGroupBox("Language")
        language_layout = QFormLayout(self.language_group)
        
        self.language_combo = QComboBox()
        self.language_combo.addItems(["English", "Español", "Français", "Deutsch", "日本語", "中文"])
        
        language_layout.addRow("Interface Language:", self.language_combo)
        
        # Performance Section
        self.performance_group = QGroupBox("Performance")
        performance_layout = QFormLayout(self.performance_group)
        
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(Config.MAX_CONCURRENT_DOWNLOADS)
        
        performance_layout.addRow("Max Concurrent Downloads:", self.concurrent_spin)
        
        # Assemble layout
        layout.addWidget(self.scheduling_group)
        layout.addWidget(self.language_group)
        layout.addWidget(self.performance_group)
        layout.addStretch()
        
        return tab

    def _create_search_tab(self) -> QWidget:
        """Create the search tab for discovering content"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # Search Input Section
        search_group = QGroupBox("Search Videos")
        search_layout = QVBoxLayout(search_group)
        
        input_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter search terms...")
        
        self.search_btn = AnimatedButton("Search")
        self.search_btn.setFixedWidth(100)
        
        input_layout.addWidget(self.search_input)
        input_layout.addWidget(self.search_btn)
        
        # Platform Selection
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["YouTube", "Vimeo", "Dailymotion", "SoundCloud"])
        
        # Results Section
        self.search_results = QListWidget()
        self.search_results.setViewMode(QListWidget.IconMode)
        self.search_results.setResizeMode(QListWidget.Adjust)
        self.search_results.setSpacing(15)
        self.search_results.setMovement(QListWidget.Static)
        self.search_results.setIconSize(QSize(120, 90))
        
        # Loading indicator
        self.search_loading = QLabel("Enter search terms and click Search")
        self.search_loading.setAlignment(Qt.AlignCenter)
        
        # Stacked widget to switch between loading and results
        self.search_stack = QStackedWidget()
        self.search_stack.addWidget(self.search_loading)
        self.search_stack.addWidget(self.search_results)
        
        search_layout.addLayout(input_layout)
        search_layout.addWidget(self.platform_combo)
        search_layout.addWidget(self.search_stack, 1)
        
        layout.addWidget(search_group)
        
        return tab

# ==================== DOWNLOAD MANAGEMENT METHODS ====================
    def start_download(self):
        urls = [url.strip() for url in self.url_input.toPlainText().split('\n') if url.strip()]
        if not urls:
            self.show_error("Error", "No URLs to download")
            return
        
        options = {
            'audio_only': self.audio_check.isChecked(),
            'quality': self.quality_combo.currentText(),
            'path': self.current_path,
            'verify': self.verify_check.isChecked(),
            'playlist': self.playlist_check.isChecked(),
            'audio_format': self.audio_format_combo.currentText(),
            'video_format': self.video_format_combo.currentText(),
            'proxy': self.proxy_input.text(),
            'retries': self.retries_spin.value(),
            'filename_template': '%(title)s [%(resolution)s].%(ext)s',
            'subtitles': self.subs_check.isChecked()  # Nueva opción
        }   
    
        self.download_manager.add_download(urls, options)
        self.url_input.clear()
        self.preview_group.setVisible(False)

    def update_download_progress(self, download_item: DownloadItem):
        """Update UI for a download's progress"""
        for i in range(self.download_list.count()):
            item = self.download_list.item(i)
            widget = self.download_list.itemWidget(item)
            if widget and widget.download_item.url == download_item.url:
                widget.update_progress(
                    download_item.progress,
                    download_item.speed,
                    download_item.eta,
                    download_item.bytes_downloaded,
                    download_item.total_bytes
                )
                break

    def on_download_complete(self, download_item: DownloadItem):
        """Handle completed download"""
        self.show_notification(
            "Download Complete",
            f"{download_item.metadata.get('title', 'File')}\nSaved to: {download_item.file_path}"
        )
        self.update_history(download_item)
        
        # Remove from active downloads list
        for i in range(self.download_list.count()):
            item = self.download_list.item(i)
            widget = self.download_list.itemWidget(item)
            if widget and widget.download_item.url == download_item.url:
                widget.update_status("completed")
                break

    def on_download_error(self, download_item: DownloadItem):
        """Handle download errors"""
        self.show_error(
            "Download Error",
            f"Failed to download: {download_item.url}\nError: {download_item.status}"
        )
        
        # Update status in the list
        for i in range(self.download_list.count()):
            item = self.download_list.item(i)
            widget = self.download_list.itemWidget(item)
            if widget and widget.download_item.url == download_item.url:
                widget.update_status("error")
                break

    def on_download_paused(self, url: str):
        """Handle download pause"""
        for i in range(self.download_list.count()):
            item = self.download_list.item(i)
            widget = self.download_list.itemWidget(item)
            if widget and widget.download_item.url == url:
                widget.update_status("paused")
                break

    def on_download_resumed(self, url: str):
        """Handle download resume"""
        for i in range(self.download_list.count()):
            item = self.download_list.item(i)
            widget = self.download_list.itemWidget(item)
            if widget and widget.download_item.url == url:
                widget.update_status("downloading")
                break

    def on_download_cancelled(self, url: str):
        """Handle download cancellation"""
        self.show_notification("Download Cancelled", f"Download cancelled: {url}")

    def on_worker_finished(self, url: str):
        """Clean up when a worker finishes"""
        # This slot is called when a worker thread completes
        pass

    def update_queue_status(self, count: int):
        """Update UI with current queue status"""
        self.setWindowTitle(f"{Config.APP_NAME} {Config.VERSION} - Queue: {count}")
        self.status_bar.showMessage(f"Downloads in queue: {count}")

    def update_preview(self, download_item: DownloadItem):
        """Update the preview panel with metadata"""
        self.preview_group.setVisible(True)
        
        self.metadata_text.setText(
            f"<b>Title:</b> {download_item.metadata.get('title', 'Unknown')}<br>"
            f"<b>Duration:</b> {self._format_duration(download_item.metadata.get('duration', 0))}<br>"
            f"<b>Uploader:</b> {download_item.metadata.get('uploader', 'Unknown')}<br>"
            f"<b>Resolution:</b> {download_item.metadata.get('resolution', 'N/A')}<br>"
            f"<b>Views:</b> {download_item.metadata.get('view_count', 0):,}<br>"
            f"<b>Upload Date:</b> {download_item.metadata.get('upload_date', 'Unknown')}"
        )
        
        thumbnail_url = download_item.metadata.get('thumbnail')
        if thumbnail_url:
            self.load_thumbnail(thumbnail_url)

    def _format_duration(self, seconds: int) -> str:
        """Convert duration in seconds to HH:MM:SS format"""
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    # ==================== HISTORY MANAGEMENT METHODS ====================
    def load_history(self):
        """Load download history from file"""
        try:
            self.history_list.clear()
            
            if os.path.exists(Config.HISTORY_FILE):
                with open(Config.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    
                    for item in history[:200]:  # Limit to 200 most recent
                        list_item = QListWidgetItem(
                            f"{item.get('date', 'Unknown')} - {item.get('title', 'Untitled')}"
                        )
                        list_item.setData(Qt.UserRole, item)
                        self.history_list.addItem(list_item)
        except Exception as e:
            logging.error(f"Failed to load history: {str(e)}")
            self.show_error("Error", f"Failed to load history: {str(e)}")

    def update_history(self, download_item: DownloadItem):
        """Update history with a new download"""
        entry = {
            'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'title': download_item.metadata.get('title', 'Unknown'),
            'url': download_item.url,
            'duration': download_item.metadata.get('duration', 0),
            'file_path': download_item.file_path,
            'status': download_item.status
        }
        
        try:
            history = []
            if os.path.exists(Config.HISTORY_FILE):
                with open(Config.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            
            history.insert(0, entry)
            
            with open(Config.HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history[:500], f, indent=2, ensure_ascii=False)
                
            # Update UI
            list_item = QListWidgetItem(
                f"{entry['date']} - {entry['title']}"
            )
            list_item.setData(Qt.UserRole, entry)
            self.history_list.insertItem(0, list_item)
            
            # Keep only 200 items in the UI
            if self.history_list.count() > 200:
                self.history_list.takeItem(200)
                
        except Exception as e:
            logging.error(f"Failed to update history: {str(e)}")
            self.show_error("Error", f"Failed to update history: {str(e)}")

    def filter_history(self):
        """Filter history based on search text"""
        filter_text = self.history_filter.text().lower()
        for i in range(self.history_list.count()):
            item = self.history_list.item(i)
            item_data = item.data(Qt.UserRole)
            match = (filter_text in item.text().lower() or 
                    (isinstance(item_data, dict) and 
                     filter_text in item_data.get('url', '').lower()))
            item.setHidden(not match)

    def clear_history(self):
        """Clear all download history"""
        reply = QMessageBox.question(
            self, 
            "Clear History",
            "Are you sure you want to clear all download history?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                with open(Config.HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump([], f)
                self.history_list.clear()
            except Exception as e:
                self.show_error("Error", f"Failed to clear history: {str(e)}")

    def show_history_context_menu(self, position):
        """Show context menu for history items"""
        item = self.history_list.itemAt(position)
        if not item:
            return
            
        menu = QMenu()
        
        open_action = menu.addAction("Open File Location")
        copy_url_action = menu.addAction("Copy URL")
        redownload_action = menu.addAction("Download Again")
        remove_action = menu.addAction("Remove from History")
        
        action = menu.exec_(self.history_list.mapToGlobal(position))
        
        if action == open_action:
            self.open_history_file_location(item)
        elif action == copy_url_action:
            self.copy_history_url(item)
        elif action == redownload_action:
            self.redownload_history_item(item)
        elif action == remove_action:
            self.remove_history_item(item)

    def open_history_file_location(self, item: QListWidgetItem):
        """Open file location in system explorer"""
        try:
            item_data = item.data(Qt.UserRole)
            if isinstance(item_data, dict) and os.path.exists(item_data.get('file_path', '')):
                file_dir = os.path.dirname(item_data['file_path'])
                QDesktopServices.openUrl(QUrl.fromLocalFile(file_dir))
            else:
                self.show_error("Error", "File location not found")
        except Exception as e:
            self.show_error("Error", f"Failed to open location: {str(e)}")

    def copy_history_url(self, item: QListWidgetItem):
        """Copy URL to clipboard"""
        try:
            item_data = item.data(Qt.UserRole)
            if isinstance(item_data, dict):
                clipboard = QApplication.clipboard()
                clipboard.setText(item_data['url'])
        except Exception as e:
            self.show_error("Error", f"Failed to copy URL: {str(e)}")

    def redownload_history_item(self, item: QListWidgetItem):
        """Prepare to download a historical item again"""
        try:
            item_data = item.data(Qt.UserRole)
            if isinstance(item_data, dict):
                self.url_input.setText(item_data['url'])
                self.tabs.setCurrentIndex(0)  # Switch to download tab
        except Exception as e:
            self.show_error("Error", f"Failed to prepare download: {str(e)}")

    def remove_history_item(self, item: QListWidgetItem):
        """Remove a single item from history"""
        try:
            row = self.history_list.row(item)
            self.history_list.takeItem(row)
            
            if os.path.exists(Config.HISTORY_FILE):
                with open(Config.HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                
                # Remove the corresponding item from the file
                item_data = item.data(Qt.UserRole)
                if isinstance(item_data, dict):
                    history = [h for h in history if h.get('url') != item_data.get('url')]
                
                with open(Config.HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(history, f, indent=2, ensure_ascii=False)
                    
        except Exception as e:
            self.show_error("Error", f"Failed to remove item: {str(e)}")

    # ==================== SCHEDULING METHODS ====================
    def add_schedule(self):
        """Add a new scheduled download"""
        urls = [url.strip() for url in self.url_input.toPlainText().split('\n') if url.strip()]
        if not urls:
            self.show_error("Error", "No URLs to schedule")
            return
            
        schedule = {
            'time': self.schedule_datetime.dateTime().toString(Qt.ISODate),
            'urls': urls,
            'repeat': self.schedule_repeat.isChecked(),
            'completed': False,
            'options': {
                'audio_only': self.audio_check.isChecked(),
                'quality': self.quality_combo.currentText(),
                'path': self.current_path,
                'verify': self.verify_check.isChecked(),
                'playlist': self.playlist_check.isChecked()
            }
        }
        
        schedules = self.settings.value("schedules", [])
        if not isinstance(schedules, list):
            schedules = []
            
        schedules.append(schedule)
        self.settings.setValue("schedules", schedules)
        
        self.update_schedule_list()
        QMessageBox.information(
            self, 
            "Schedule Added", 
            f"Download scheduled for {schedule['time']}"
        )

    def remove_schedule(self):
        """Remove selected scheduled download"""
        selected = self.schedule_list.currentRow()
        if selected >= 0:
            schedules = self.settings.value("schedules", [])
            if isinstance(schedules, list) and selected < len(schedules):
                del schedules[selected]
                self.settings.setValue("schedules", schedules)
                self.update_schedule_list()

    def update_schedule_list(self):
        """Refresh the schedule list UI"""
        self.schedule_list.clear()
        schedules = self.settings.value("schedules", [])
        
        if not isinstance(schedules, list):
            schedules = []
            
        for schedule in schedules:
            if not isinstance(schedule, dict):
                continue
                
            status = "✅" if schedule.get('completed', False) else "⏰"
            time_str = QDateTime.fromString(schedule.get('time', ''), Qt.ISODate).toString(Qt.DefaultLocaleShortDate)
            item = QListWidgetItem(
                f"{status} {time_str} - {len(schedule.get('urls', []))} URLs"
            )
            item.setData(Qt.UserRole, schedule)
            self.schedule_list.addItem(item)
            
        self.remove_schedule_btn.setEnabled(self.schedule_list.count() > 0)

    def check_scheduled_downloads(self):
        """Check and start any scheduled downloads"""
        now = QDateTime.currentDateTime()
        schedules = self.settings.value("schedules", [])
        updated = False
        
        if not isinstance(schedules, list):
            schedules = []
            
        for idx, schedule in enumerate(schedules):
            if not isinstance(schedule, dict):
                continue
                
            if schedule.get('completed', False):
                continue
                
            scheduled_time = QDateTime.fromString(schedule.get('time', ''), Qt.ISODate)
            if scheduled_time.isValid() and now >= scheduled_time:
                self.start_scheduled_download(schedule)
                
                if schedule.get('repeat', False):
                    # Reschedule for next day
                    new_time = scheduled_time.addDays(1)
                    schedules[idx]['time'] = new_time.toString(Qt.ISODate)
                else:
                    schedules[idx]['completed'] = True
                    
                updated = True
                
        if updated:
            self.settings.setValue("schedules", schedules)
            self.update_schedule_list()

    def start_scheduled_download(self, schedule: dict):
        """Start a scheduled download batch"""
        if not isinstance(schedule, dict):
            return
            
        urls = schedule.get('urls', [])
        options = schedule.get('options', {})
        
        if urls and isinstance(options, dict):
            # Ensure path exists
            path = options.get('path', self.current_path)
            os.makedirs(path, exist_ok=True)
            
            self.download_manager.add_download(urls, options)
            self.show_notification(
                "Scheduled Download Started", 
                f"Started {len(urls)} scheduled downloads"
            )

    # ==================== SEARCH METHODS ====================
    def perform_search(self):
        """Perform a video search on the selected platform"""
        query = self.search_input.text().strip()
        if not query:
            self.show_error("Error", "Please enter a search term")
            return
            
        platform = self.platform_combo.currentText().lower()
        
        # Show loading state
        self.search_loading.setText("Searching...")
        self.search_stack.setCurrentIndex(0)
        
        # Run search in background
        def search_task():
            try:
                ydl_opts = {
                    'extract_flat': True,
                    'quiet': True,
                    'no_warnings': True,
                    'default_search': 'ytsearch10:',
                    'source_address': '0.0.0.0'
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    results = ydl.extract_info(query, download=False)
                    
                    if not results or 'entries' not in results:
                        return []
                        
                    return results['entries']
                    
            except Exception as e:
                ErrorHandler.handle(e, "Search failed")
                return []

        def update_results(results):
            self.search_results.clear()
            
            if not results:
                self.search_loading.setText("No results found")
                return
                
            self.search_stack.setCurrentIndex(1)
            
            for result in results:
                if not isinstance(result, dict):
                    continue
                    
                item = QListWidgetItem(result.get('title', 'Untitled'))
                item.setData(Qt.UserRole, result.get('url'))
                
                # Set tooltip with more info
                tooltip = (
                    f"<b>Title:</b> {result.get('title', 'N/A')}<br>"
                    f"<b>Duration:</b> {result.get('duration', 'N/A')}s<br>"
                    f"<b>Uploader:</b> {result.get('uploader', 'N/A')}<br>"
                    f"<b>Views:</b> {result.get('view_count', 'N/A')}"
                )
                item.setToolTip(tooltip)
                
                # Load thumbnail in background
                thumbnail = result.get('thumbnail')
                if thumbnail:
                    self.load_search_thumbnail(thumbnail, item)
                
                self.search_results.addItem(item)

        # Worker function to handle the background task
        def worker():
            results = search_task()
            QMetaObject.invokeMethod(self, "update_search_results", 
                                   Qt.QueuedConnection,
                                   Q_ARG(list, results))

        # Run in background thread
        QThreadPool.globalInstance().start(worker)

    @pyqtSlot(list)
    def update_search_results(self, results):
        """Update UI with search results (called from main thread)"""
        if not results:
            self.search_loading.setText("No results found")
            self.search_stack.setCurrentIndex(0)
        else:
            self.search_stack.setCurrentIndex(1)
            self.search_results.clear()
            
            for result in results:
                item = QListWidgetItem(result.get('title', 'Untitled'))
                item.setData(Qt.UserRole, result.get('url'))
                self.search_results.addItem(item)

    def load_search_thumbnail(self, url: str, item: QListWidgetItem):
        """Load and set thumbnail for a search result item"""
        # Generate cache filename
        thumbnail_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(Config.THUMBNAIL_CACHE, f"{thumbnail_hash}.jpg")
        
        def download_thumbnail():
            try:
                if os.path.exists(cache_path):
                    # Load from cache
                    image = QImage(cache_path)
                else:
                    # Download and cache
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        image = QImage()
                        image.loadFromData(response.content)
                        image.save(cache_path, "JPEG")
                
                # Set icon if item still exists
                if item and self.search_results.row(item) >= 0:
                    icon = QIcon(QPixmap.fromImage(image).scaled(
                        120, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                    item.setIcon(icon)
                    
            except Exception as e:
                logging.error(f"Failed to load thumbnail: {str(e)}")

        # Run in background thread
        QThreadPool.globalInstance().start(download_thumbnail)

    def add_search_result_to_downloads(self, item: QListWidgetItem):
        """Add a search result to the download queue"""
        url = item.data(Qt.UserRole)
        if url:
            self.url_input.setText(url)
            self.tabs.setCurrentIndex(0)  # Switch to download tab

    # ==================== UTILITY METHODS ====================
    def load_thumbnail(self, url: str):
        """Load thumbnail from URL with caching"""
        thumbnail_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(Config.THUMBNAIL_CACHE, f"{thumbnail_hash}.jpg")
        
        def download_thumbnail():
            try:
                if os.path.exists(cache_path):
                    # Load from cache
                    pixmap = QPixmap(cache_path)
                else:
                    # Download and cache
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        image = QImage()
                        image.loadFromData(response.content)
                        image.save(cache_path, "JPEG")
                        pixmap = QPixmap.fromImage(image)
                
                # Update UI
                if pixmap and not pixmap.isNull():
                    self.thumbnail_label.setPixmap(pixmap.scaled(
                        200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    ))
                    
            except Exception as e:
                logging.error(f"Failed to load thumbnail: {str(e)}")

        # Run in background
        QThreadPool.globalInstance().start(download_thumbnail)

    def select_download_path(self):
        """Open dialog to select download directory"""
        path = QFileDialog.getExistingDirectory(
            self, 
            "Select Download Folder", 
            self.current_path,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if path:
            self.current_path = path
            self.path_label.setText(path)
            self.settings.setValue("download_path", path)

    def toggle_theme(self):
        """Toggle between dark and light theme"""
        self.dark_mode = not self.dark_mode
        self.settings.setValue("dark_mode", self.dark_mode)
        AppTheme.apply_theme(self, "dark" if self.dark_mode else "light")
        self.toggle_theme_btn.setText("🌙" if self.dark_mode else "☀️")

    def update_audio_ui(self):
        """Update UI when audio mode is toggled"""
        checked = self.audio_check.isChecked()
        self.quality_combo.setEnabled(not checked)
        self.video_format_combo.setEnabled(not checked)
        self.audio_format_combo.setEnabled(checked)
        self.settings.setValue("audio_mode", checked)

    def change_language(self, language: str):
        """Change application language"""
        lang_map = {
            "English": "en",
            "Español": "es",
            "Français": "fr",
            "Deutsch": "de",
            "日本語": "ja",
            "中文": "zh"
        }
        
        lang_code = lang_map.get(language, "en")
        if lang_code != self.current_language:
            self.current_language = lang_code
            self.settings.setValue("language", lang_code)
            
            # In a real implementation, we would reload the UI with translations
            # This would require setting up proper translation files (.qm)
            QMessageBox.information(
                self,
                "Language Changed",
                f"Language will change to {language} after restart"
            )

    def load_settings(self):
        """Load application settings"""
        self.quality_combo.setCurrentText(self.settings.value("quality", "1080p"))
        self.audio_check.setChecked(self.settings.value("audio_mode", False, type=bool))
        self.audio_format_combo.setCurrentText(self.settings.value("audio_format", "mp3"))
        self.video_format_combo.setCurrentText(self.settings.value("video_format", "mp4"))
        self.proxy_input.setText(self.settings.value("proxy", ""))
        self.retries_spin.setValue(int(self.settings.value("retries", 3)))
        self.verify_check.setChecked(self.settings.value("verify", False, type=bool))
        self.playlist_check.setChecked(self.settings.value("playlist", True, type=bool))
        self.concurrent_spin.setValue(int(self.settings.value("max_concurrent", Config.MAX_CONCURRENT_DOWNLOADS)))
        
        # Update UI based on settings
        self.update_audio_ui()
        self.update_schedule_list()
        
        # Set language
        lang_code = self.settings.value("language", "en")
        lang_map = {
            "en": "English",
            "es": "Español",
            "fr": "Français",
            "de": "Deutsch",
            "ja": "日本語",
            "zh": "中文"
        }
        
        current_lang = lang_map.get(lang_code, "English")
        index = self.language_combo.findText(current_lang)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)

    def save_settings(self):
        """Save application settings"""
        self.settings.setValue("quality", self.quality_combo.currentText())
        self.settings.setValue("audio_mode", self.audio_check.isChecked())
        self.settings.setValue("audio_format", self.audio_format_combo.currentText())
        self.settings.setValue("video_format", self.video_format_combo.currentText())
        self.settings.setValue("proxy", self.proxy_input.text())
        self.settings.setValue("retries", self.retries_spin.value())
        self.settings.setValue("verify", self.verify_check.isChecked())
        self.settings.setValue("playlist", self.playlist_check.isChecked())
        self.settings.setValue("max_concurrent", self.concurrent_spin.value())
        self.settings.setValue("download_path", self.current_path)
        self.settings.setValue("dark_mode", self.dark_mode)
        self.settings.setValue("language", self.current_language)
        
        self.download_manager.load_settings()

    def show_notification(self, title: str, message: str):
        """Show system tray notification"""
        self.tray.showMessage(title, message, QSystemTrayIcon.Information, 3000)

    def show_error(self, title: str, message: str):
        """Show error message dialog"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    def show_about(self):
        """Show about dialog"""
        about_text = (
            f"<h1>{Config.APP_NAME} {Config.VERSION}</h1>"
            "<p>Download multimedia content from multiple platforms</p>"
            "<p><b>Supported sites:</b> YouTube, TikTok, Instagram, Twitter, "
            "Twitch, Reddit, Dailymotion, SoundCloud, Vimeo, Facebook, "
            "LinkedIn, Rumble, Bilibili, Odysee</p>"
            "<p><b>Support:</b> saikanet.studio@gmail.com</p>"
            "<p><b>Developed by:</b> Dragoland</p>"
            "<p>Thank you for using our software!</p>"
        )
    
        msg = QMessageBox(self)
        msg.setWindowTitle("About")
        msg.setTextFormat(Qt.RichText)
        msg.setText(about_text)
        msg.setIconPixmap(QPixmap(Utils.resource_path(Config.ICON)).scaled(64, 64))
        msg.exec_()

    def open_donation(self):
        """Open donation link in browser"""
        webbrowser.open("https://tppay.me/m7eghft5")

    def tray_activated(self, reason):
        """Handle system tray activation"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.activateWindow()
            self.raise_()

    def closeEvent(self, event):
        """Handle window close event"""
        self.save_settings()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.tray.hide()
        event.accept()

# ==================== APPLICATION ENTRY ====================
if __name__ == "__main__":
    # High DPI support
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    
    # Set application info
    app.setApplicationName(Config.APP_NAME)
    app.setApplicationVersion(Config.VERSION)
    app.setOrganizationName("SaikaNET Studio")
    app.setWindowIcon(QIcon(Utils.resource_path(Config.ICON)))
    
    # Initialize translator
    translator = Translator()
    translator.set_language("en", app)  # Default to English
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())

    