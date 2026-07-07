#!/usr/bin/env python3
"""
窗口随机切换器 — 双击即用，定时随机切换前台窗口，模拟真人操作。
纯 Python 标准库实现，无需 pip 安装任何依赖。
兼容 Windows 10 / Windows 11。

使用方法：
  1. 双击 window_switcher.pyw 即可启动
  2. 系统托盘会出现圆形图标（灰色=已停止，绿色=运行中）
  3. 右键图标弹出菜单：开始切换 / 停止切换 / 设置间隔 / 退出
  4. 左键图标：快速切换一次
"""

import ctypes
from ctypes import wintypes, Structure, POINTER, sizeof, byref, cast
import struct
import random
import time
import threading
import json
import os
import sys
import tempfile
import atexit
import tkinter as tk
from tkinter import simpledialog
from pathlib import Path

import logging
from logging.handlers import RotatingFileHandler

# 补充 wintypes 中缺失的指针大小整数类型
if ctypes.sizeof(ctypes.c_void_p) == 8:
    LONG_PTR = ctypes.c_longlong
    UINT_PTR = ctypes.c_ulonglong
else:
    LONG_PTR = ctypes.c_long
    UINT_PTR = ctypes.c_ulong

# =============================================================================
# 日志系统
# =============================================================================

def _setup_logging():
    """配置日志：文件轮转（500KB × 5 个备份）+ 控制台输出。"""
    try:
        script_dir = Path(sys.argv[0]).parent.resolve()
    except Exception:
        script_dir = Path.cwd()
    log_path = script_dir / "switcher_log.txt"

    logger = logging.getLogger("switcher")
    logger.setLevel(logging.DEBUG)

    # 文件 handler：轮转，最多 5 个备份
    fh = RotatingFileHandler(
        str(log_path), maxBytes=500 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)

    # 控制台 handler：仅 WARNING 及以上
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    return logger

log = _setup_logging()

# =============================================================================
# ICO 图标生成（纯 Python，无外部依赖）
# =============================================================================

def _generate_ico_bytes(size=32, r=76, g=175, b=80):
    """生成一个带圆形图案的 .ico 文件（字节数据）。
    使用 32-bit ARGB 格式，圆形外部为透明。
    """
    # BITMAPINFOHEADER (40 bytes)
    bih = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        size,         # biWidth
        size * 2,    # biHeight (双倍高度 — ICO 特有，包含 AND mask)
        1,            # biPlanes
        32,           # biBitCount
        0,            # biCompression (BI_RGB)
        0,            # biSizeImage (可为0)
        0, 0, 0, 0,   # 其余字段
    )

    # 像素数据（32-bit BGRA，自底向上）
    pixels = bytearray()
    center = (size - 1) / 2.0
    radius = size / 2.0 - 1.5

    # BMP 从底行到顶行
    for y in range(size - 1, -1, -1):
        for x in range(size):
            dx = x - center
            dy = y - center
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= radius:
                pixels.extend([b, g, r, 255])  # BGRA 不透明
            else:
                pixels.extend([0, 0, 0, 0])     # 完全透明

    # AND mask (1 bit per pixel, 4-byte aligned per row)
    and_row_bytes = (size + 7) // 8
    and_row_padded = (and_row_bytes + 3) // 4 * 4
    and_mask = bytearray(and_row_padded * size)  # 全0 = 所有像素为屏幕像素

    image_data = bih + bytes(pixels) + bytes(and_mask)

    # ICO 目录项 (16 bytes)
    data_offset = 6 + 16  # header + 1 entry
    entry = struct.pack(
        "<BBBBHHII",
        size if size < 256 else 0,  # width
        size if size < 256 else 0,  # height
        0,                            # palette
        0,                            # reserved
        1,                            # color planes
        32,                           # bits per pixel
        len(image_data),              # data size
        data_offset,                  # data offset
    )

    # ICO 头 (6 bytes)
    header = struct.pack("<HHH", 0, 1, 1)  # reserved, type=ICO, count=1

    return header + entry + image_data


def _create_temp_ico(color=(76, 175, 80)):
    """创建临时 .ico 文件并返回路径。应用退出时自动清理。"""
    ico_bytes = _generate_ico_bytes(size=32, r=color[0], g=color[1], b=color[2])
    fd, path = tempfile.mkstemp(suffix=".ico", prefix="switcher_")
    with os.fdopen(fd, "wb") as f:
        f.write(ico_bytes)
    atexit.register(lambda: _safe_unlink(path))
    return path


def _safe_unlink(path):
    """安全删除临时文件。"""
    try:
        os.unlink(path)
    except OSError:
        pass

# =============================================================================
# Windows API 类型与常量
# =============================================================================

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi
shell32 = ctypes.windll.shell32

# --- 窗口操作 ---
SW_RESTORE = 9
SW_SHOW = 5
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
DWMWA_CLOAKED = 14

# --- 系统托盘 ---
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
NIF_MESSAGE = 1
NIF_ICON = 2
NIF_TIP = 4
NIF_STATE = 8
NIF_INFO = 0x10
NIF_GUID = 0x20
NIIF_NONE = 0
NIIF_INFO = 1
NIS_HIDDEN = 1

# --- 窗口子类化 ---
GWLP_WNDPROC = -4
WM_USER = 0x0400
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
WM_TASKBARCREATED = 0  # 通过 RegisterWindowMessage 获取
WM_DESTROY = 0x0002

# 自定义消息 ID
WM_TRAY_CALLBACK = WM_USER + 100

# --- 弹出菜单 ---
TPM_LEFTALIGN = 0
TPM_RIGHTBUTTON = 2
TPM_BOTTOMALIGN = 0
TPM_TOPALIGN = 0
TPM_RETURNCMD = 0x100  # 让 TrackPopupMenu 返回选中的菜单项 ID

# =============================================================================
# Windows API 结构体
# =============================================================================

class POINT(Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class NOTIFYICONDATAW(Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", wintypes.BYTE * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


# =============================================================================
# WinAPI 函数签名
# =============================================================================

# 系统托盘
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL

# 窗口子类化（LONG_PTR 在 64 位系统为 c_longlong，32 位为 c_long）
# SetWindowLongPtrW 第三个参数用 c_void_p 以接受函数指针
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.SetWindowLongPtrW.restype = LONG_PTR

user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = LONG_PTR

user32.CallWindowProcW.argtypes = [LONG_PTR, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CallWindowProcW.restype = LONG_PTR

user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND

# 窗口枚举与操作
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL

user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL

# DWM 隐藏窗口检测
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

# 图标加载
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HICON

user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010

# 鼠标位置
user32.GetCursorPos.argtypes = [POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

# 弹出菜单
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = wintypes.HMENU

user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, UINT_PTR, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL

user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = wintypes.BOOL

user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL

user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.BOOL]
user32.SetMenuDefaultItem.restype = wintypes.BOOL

MF_STRING = 0
MF_SEPARATOR = 0x800
MF_DEFAULT = 0x1000
MF_GRAYED = 1

# 获取顶层窗口 (用于弹出菜单定位)
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

# SendMessage
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = LONG_PTR

WM_NULL = 0

# --- 用户空闲检测 ---
class LASTINPUTINFO(Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]

user32.GetLastInputInfo.argtypes = [POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL

kernel32.GetTickCount.argtypes = []
kernel32.GetTickCount.restype = wintypes.DWORD

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE

kernel32.GetLastError.argtypes = []
kernel32.GetLastError.restype = wintypes.DWORD

# =============================================================================
# 窗口管理器
# =============================================================================

class WindowManager:
    """封装所有 Windows 窗口枚举与切换操作。"""

    @staticmethod
    def is_window_cloaked(hwnd):
        """检查窗口是否为 Win8+ 隐藏窗口（不可见的 UWP 应用）。"""
        cloaked = ctypes.c_int(0)
        result = dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, byref(cloaked), sizeof(cloaked)
        )
        return result == 0 and cloaked.value != 0

    @staticmethod
    def enum_visible_windows():
        """枚举当前所有可见且有标题的顶层窗口。
        返回: [(hwnd, title), ...]
        """
        windows = []
        current_pid = os.getpid()

        def callback(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            if WindowManager.is_window_cloaked(hwnd):
                return True
            title_len = user32.GetWindowTextLengthW(hwnd)
            if title_len == 0:
                return True
            buf = ctypes.create_unicode_buffer(title_len + 1)
            user32.GetWindowTextW(hwnd, buf, title_len + 1)
            title = buf.value.strip()
            if not title:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, byref(pid))
            if pid.value == current_pid:
                return True
            windows.append((hwnd, title))
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return windows

    @staticmethod
    def get_idle_seconds():
        """获取用户最后一次输入（键盘/鼠标）距今的秒数。
        返回 -1 表示无法获取。
        """
        lii = LASTINPUTINFO()
        lii.cbSize = sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(byref(lii)):
            return -1
        tick = kernel32.GetTickCount()
        idle_ms = tick - lii.dwTime
        # 处理 tick 回绕（系统运行超过 49.7 天）
        if idle_ms < 0:
            idle_ms = 0
        return idle_ms // 1000

    @staticmethod
    def get_foreground_window():
        """获取当前前台窗口句柄。"""
        return user32.GetForegroundWindow()

    @staticmethod
    def switch_to_window(hwnd):
        """切换到指定窗口。
        使用 AttachThreadInput 获取前台切换权限，
        并先还原最小化的窗口。
        """
        # 还原最小化窗口
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.05)

        # 获取当前前台线程并附加输入
        fg_hwnd = user32.GetForegroundWindow()
        current_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)

        if fg_thread and fg_thread != current_thread:
            user32.AttachThreadInput(current_thread, fg_thread, True)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(current_thread, fg_thread, False)
        else:
            user32.SetForegroundWindow(hwnd)


# =============================================================================
# 配置管理
# =============================================================================

class Config:
    """持久化配置，以 JSON 文件保存在脚本同目录。"""

    DEFAULT = {
        "min_interval": 120,       # 最小间隔（秒）
        "max_interval": 300,       # 最大间隔（秒）
        "burst_enabled": True,     # 是否启用连切模式
        "burst_chance": 0.15,      # 连切触发概率
        "idle_threshold": 60,      # 空闲阈值（秒），0=关闭
        "auto_stop_time": "18:00", # 每日自动停止时间，"":关闭
    }

    def __init__(self, path=None):
        if path is None:
            try:
                script_dir = Path(sys.argv[0]).parent.resolve()
            except Exception:
                script_dir = Path.cwd()
            path = script_dir / "switcher_config.json"
        self.path = Path(path)
        self.data = dict(self.DEFAULT)
        self.load()

    def load(self):
        """从文件加载配置。"""
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                for key in self.DEFAULT:
                    if key in loaded:
                        self.data[key] = loaded[key]
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        """将配置写入文件。"""
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except IOError:
            pass

    @property
    def min_interval(self):
        return self.data["min_interval"]

    @property
    def max_interval(self):
        return self.data["max_interval"]

    @property
    def burst_enabled(self):
        return self.data["burst_enabled"]

    @property
    def burst_chance(self):
        return self.data["burst_chance"]


# =============================================================================
# 切换引擎
# =============================================================================

class SwitcherEngine:
    """后台线程执行的窗口切换引擎。"""

    def __init__(self, config: Config):
        self.config = config
        self.running = False
        self._stop_event = threading.Event()
        self._thread = None
        self._last_hwnd = None
        self._lock = threading.Lock()
        self._auto_stop_triggered_date = None  # 记录触发过的日期
        self._notify_stop_cb = None  # 自动停止时的托盘更新回调

    def set_stop_callback(self, callback):
        """设置自动停止时的回调函数（用于更新托盘图标）。"""
        self._notify_stop_cb = callback

    def start(self):
        """启动切换线程。"""
        if self.running:
            return
        log.info("Switcher started")
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="switcher-thread"
        )
        self._thread.start()

    def stop(self):
        """停止切换线程。"""
        if not self.running:
            return
        log.info("Switcher stopped")
        self.running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def switch_now(self):
        """立即执行一次窗口切换（供手动触发）。"""
        if self.running:
            return  # 引擎运行中时由线程管理
        self._switch_once()

    def _run(self):
        """切换线程主循环 — 随机间隔 + 随机连切 + 空闲检测 + 自动停止。"""
        while not self._stop_event.is_set():
            try:
                self._check_auto_stop()
                self._do_switch_cycle()
            except Exception as e:
                log.debug("Switch cycle error: %s", e)

            wait = random.uniform(
                self.config.min_interval,
                self.config.max_interval,
            )
            self._stop_event.wait(wait)

    def _check_auto_stop(self):
        """检查是否到达每日自动停止时间。"""
        stop_time_str = self.config.data.get("auto_stop_time", "")
        if not stop_time_str or not stop_time_str.strip():
            return  # 功能关闭

        try:
            from datetime import datetime, date
            now = datetime.now()
            target_h, target_m = map(int, stop_time_str.strip().split(":"))
            target_time = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)

            # 只在达到后的 5 分钟窗口内触发（防止超时等待期间重复检查）
            if now < target_time:
                return  # 还没到时间

            if (now - target_time).total_seconds() > 300:
                return  # 超过窗口期

            today = date.today()
            if self._auto_stop_triggered_date == today:
                return  # 今天已触发过

            self._auto_stop_triggered_date = today
            log.info("Auto-stop triggered at %s", stop_time_str.strip())
            self.stop()

            # 通知托盘更新（通过 after 回调）
            if hasattr(self, '_notify_stop_cb') and self._notify_stop_cb:
                self._notify_stop_cb()

        except (ValueError, Exception):
            pass  # 时间格式异常，静默跳过

    def _do_switch_cycle(self):
        """执行一次切换周期（可能包含连切）。"""
        should_burst = (
            self.config.burst_enabled
            and random.random() < self.config.burst_chance
        )

        if should_burst:
            times = random.randint(2, 3)
            for i in range(times):
                if self._stop_event.is_set():
                    return
                self._switch_once()
                if i < times - 1:
                    self._stop_event.wait(random.uniform(0.5, 1.5))
        else:
            self._switch_once()

    def _switch_once(self):
        """执行一次窗口切换（含空闲检测）。"""
        # 空闲检测：如果用户最近有操作，跳过本次切换
        threshold = self.config.data.get("idle_threshold", 0)
        if threshold > 0:
            idle_sec = WindowManager.get_idle_seconds()
            if 0 <= idle_sec < threshold:
                log.debug("Idle skip: user active %ds ago", idle_sec)
                return  # 用户正在操作，不切

        windows = WindowManager.enum_visible_windows()
        if not windows:
            log.debug("No visible windows found")
            return

        fg = WindowManager.get_foreground_window()
        candidates = windows
        if len(windows) > 1 and fg:
            candidates = [(h, t) for h, t in windows if h != fg]
            if not candidates:
                candidates = windows

        target_hwnd, _ = random.choice(candidates)

        with self._lock:
            if len(candidates) > 1 and target_hwnd == self._last_hwnd:
                others = [(h, t) for h, t in candidates if h != self._last_hwnd]
                if others:
                    target_hwnd, _ = random.choice(others)
            self._last_hwnd = target_hwnd

        log.debug("Switched to: %s", target_title)
        WindowManager.switch_to_window(target_hwnd)


# =============================================================================
# 系统托盘应用（ctypes Shell_NotifyIcon + tkinter 消息泵）
# =============================================================================

# 全局 WndProc 回调类型
WNDPROC_TYPE = ctypes.WINFUNCTYPE(
    LONG_PTR, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class TrayApp:
    """系统托盘应用程序。
    使用 Shell_NotifyIcon 创建托盘图标，
    通过子类化 tkinter 的窗口过程处理托盘消息。
    """

    # Win32 菜单命令 ID
    CMD_START = 1001
    CMD_STOP = 1002
    CMD_SETTINGS = 1003
    CMD_SWITCH_NOW = 1004
    CMD_EXIT = 1005

    def __init__(self):
        self.config = Config()
        self.engine = SwitcherEngine(self.config)
        self.engine.set_stop_callback(lambda: self._root.after(0, self._update_tray))
        self._running = True

        # 创建图标文件
        self._ico_green = _create_temp_ico((76, 175, 80))
        self._ico_gray = _create_temp_ico((158, 158, 158))

        # 托盘数据
        self._nid = NOTIFYICONDATAW()
        self._tray_added = False

        # tkinter 根窗口（隐藏，仅用于消息泵）
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("WindowSwitcher_TrayHost")
        self._root.protocol("WM_DELETE_WINDOW", lambda: None)  # 禁用关闭按钮

        # 强制创建窗口句柄
        self._root.update_idletasks()

    def run(self):
        """启动托盘应用（阻塞主线程）。"""
        # 获取 HWND
        self._hwnd = self._get_tk_hwnd()
        if not self._hwnd:
            print("错误: 无法获取 tkinter 窗口句柄", file=sys.stderr)
            return

        # 注册 TaskbarCreated 消息
        global WM_TASKBARCREATED
        WM_TASKBARCREATED = user32.RegisterWindowMessageW("TaskbarCreated")

        # 子类化窗口过程
        self._original_wndproc = user32.GetWindowLongPtrW(self._hwnd, GWLP_WNDPROC)
        self._new_wndproc = WNDPROC_TYPE(self._wnd_proc)
        user32.SetWindowLongPtrW(self._hwnd, GWLP_WNDPROC, self._new_wndproc)

        # 添加托盘图标
        self._add_tray_icon(active=False)

        # 启动消息循环
        try:
            self._root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup()

    def _get_tk_hwnd(self):
        """获取 tkinter 根窗口的原生 HWND。"""
        try:
            # tkinter 的 frame() 返回十六进制字符串格式的 HWND
            hwnd_str = self._root.frame()
            if hwnd_str:
                return wintypes.HWND(int(hwnd_str, 16))
        except Exception:
            pass
        # 备用方案：通过窗口标题查找
        try:
            hwnd = user32.FindWindowW(None, "WindowSwitcher_TrayHost")
            if hwnd:
                return hwnd
        except Exception:
            pass
        return None

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        """自定义窗口过程 — 处理托盘回调消息。"""
        if msg == WM_TRAY_CALLBACK:
            evt = lparam & 0xFFFF
            if evt == WM_RBUTTONUP:
                self._show_popup_menu()
            elif evt == WM_LBUTTONUP:
                self._on_tray_click()
            return 0
        elif msg == WM_TASKBARCREATED:
            # 资源管理器重启后重新创建托盘图标
            self._add_tray_icon(active=self.engine.running)
            return 0
        elif msg == WM_DESTROY:
            self._cleanup()
            return 0

        # 调用原始窗口过程
        return user32.CallWindowProcW(
            self._original_wndproc, hwnd, msg, wparam, lparam
        )

    def _add_tray_icon(self, active=False):
        """添加或更新托盘图标。"""
        icon_path = self._ico_green if active else self._ico_gray
        hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if not hicon:
            # 如果 32x32 加载失败，尝试系统默认小图标尺寸
            hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)

        tip_text = "窗口切换器 — " + ("运行中" if active else "已停止")

        self._nid = NOTIFYICONDATAW()
        self._nid.cbSize = sizeof(NOTIFYICONDATAW)
        self._nid.hWnd = self._hwnd
        self._nid.uID = 1
        self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self._nid.uCallbackMessage = WM_TRAY_CALLBACK
        self._nid.hIcon = hicon or 0
        self._nid.szTip = tip_text
        self._nid.dwState = 0
        self._nid.dwStateMask = 0

        if self._tray_added:
            shell32.Shell_NotifyIconW(NIM_MODIFY, byref(self._nid))
        else:
            shell32.Shell_NotifyIconW(NIM_ADD, byref(self._nid))
            self._tray_added = True

        # 通知托盘使用新版 API（Win2K+）
        self._nid.uTimeoutOrVersion = 4  # NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(NIM_SETVERSION, byref(self._nid))

    def _update_tray(self):
        """根据引擎状态更新托盘图标外观。"""
        icon_path = self._ico_green if self.engine.running else self._ico_gray
        hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if not hicon:
            hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)

        tip_text = "窗口切换器 — " + ("运行中" if self.engine.running else "已停止")

        self._nid.hIcon = hicon or 0
        self._nid.szTip = tip_text
        self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        shell32.Shell_NotifyIconW(NIM_MODIFY, byref(self._nid))

    def _show_popup_menu(self):
        """在光标位置显示 Win32 右键弹出菜单。"""
        running = self.engine.running

        # 创建弹出菜单
        menu = user32.CreatePopupMenu()

        if running:
            user32.AppendMenuW(menu, MF_STRING, self.CMD_STOP, "⏹  停止切换")
            user32.AppendMenuW(menu, MF_STRING, self.CMD_SWITCH_NOW, "🔄 立即切换")
        else:
            user32.AppendMenuW(menu, MF_STRING, self.CMD_START, "▶  开始切换")
            user32.AppendMenuW(menu, MF_STRING, self.CMD_SWITCH_NOW, "🔄 立即切换")

        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, self.CMD_SETTINGS, "⚙  设置间隔...")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)

        status_text = "📊 状态: 运行中" if running else "📊 状态: 已停止"
        user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, status_text)
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, self.CMD_EXIT, "❌  退出")

        # 设置默认项
        user32.SetMenuDefaultItem(menu, self.CMD_STOP if running else self.CMD_START, False)

        # 获取光标位置
        pt = POINT()
        user32.GetCursorPos(byref(pt))

        # 确保窗口能接收菜单消息
        user32.SetForegroundWindow(self._hwnd)

        # 显示并跟踪菜单
        cmd = user32.TrackPopupMenu(
            menu,
            TPM_LEFTALIGN | TPM_BOTTOMALIGN | TPM_RIGHTBUTTON | TPM_RETURNCMD,
            pt.x, pt.y,
            0,        # 保留参数
            self._hwnd,
            None,     # 不限制矩形
        )

        user32.DestroyMenu(menu)

        # 处理菜单选择
        self._handle_menu_cmd(cmd)

        # 恢复消息状态
        user32.SendMessageW(self._hwnd, WM_NULL, 0, 0)

    def _handle_menu_cmd(self, cmd):
        """处理弹出菜单的命令。"""
        if cmd == self.CMD_START:
            self._on_start()
        elif cmd == self.CMD_STOP:
            self._on_stop()
        elif cmd == self.CMD_SWITCH_NOW:
            self._on_switch_now()
        elif cmd == self.CMD_SETTINGS:
            # 使用 after 延迟执行，避免阻塞菜单消息循环
            self._root.after(100, self._on_settings)
        elif cmd == self.CMD_EXIT:
            self._root.after(100, self._on_exit)

    def _on_tray_click(self):
        """左键点击托盘图标 — 立即切换一次窗口。"""
        t = threading.Thread(target=self._switch_now_thread, daemon=True)
        t.start()

    def _switch_now_thread(self):
        """在后台线程执行立即切换。"""
        self.engine.switch_now()

    def _on_start(self):
        """开始切换。"""
        self.engine.start()
        self._update_tray()

    def _on_stop(self):
        """停止切换。"""
        self.engine.stop()
        self._update_tray()

    def _on_switch_now(self):
        """手动触发一次切换。"""
        t = threading.Thread(target=self.engine.switch_now, daemon=True)
        t.start()

    def _on_settings(self):
        """打开设置对话框 — 配置所有参数。"""
        try:
            dialog = tk.Toplevel(self._root)
            dialog.withdraw()
            dialog.attributes("-topmost", True)

            # 最小间隔
            min_val = simpledialog.askinteger(
                "Settings - Min Interval",
                "Min interval (seconds)\nCurrent: %d\n\nShortest time between switches" % self.config.min_interval,
                initialvalue=self.config.min_interval,
                minvalue=10, maxvalue=3600,
                parent=dialog,
            )
            if min_val is not None:
                self.config.data["min_interval"] = min_val

            # 最大间隔
            max_val = simpledialog.askinteger(
                "Settings - Max Interval",
                "Max interval (seconds)\nCurrent: %d\n\nLongest time between switches" % self.config.max_interval,
                initialvalue=self.config.max_interval,
                minvalue=10, maxvalue=3600,
                parent=dialog,
            )
            if max_val is not None:
                if max_val < self.config.data["min_interval"]:
                    max_val = self.config.data["min_interval"]
                self.config.data["max_interval"] = max_val

            if self.config.data["max_interval"] < self.config.data["min_interval"]:
                self.config.data["max_interval"] = self.config.data["min_interval"]

            # 空闲阈值
            idle_threshold = self.config.data.get("idle_threshold", 60)
            idle_val = simpledialog.askinteger(
                "Settings - Idle Threshold",
                "Idle threshold (seconds, 0=off)\nCurrent: %d\n\nSkip switch if user active within N seconds" % idle_threshold,
                initialvalue=idle_threshold,
                minvalue=0, maxvalue=600,
                parent=dialog,
            )
            if idle_val is not None:
                self.config.data["idle_threshold"] = idle_val

            # 自动停止时间
            auto_stop = self.config.data.get("auto_stop_time", "18:00")
            stop_val = simpledialog.askstring(
                "Settings - Auto Stop Time",
                "Auto stop time (HH:MM, empty=off)\nCurrent: %s\n\nAuto stop switching at this time daily" % auto_stop,
                initialvalue=auto_stop,
                parent=dialog,
            )
            if stop_val is not None:
                # 简单校验 HH:MM 格式
                stop_val = stop_val.strip()
                if stop_val == "" or (len(stop_val) == 5 and stop_val[2] == ":"):
                    self.config.data["auto_stop_time"] = stop_val

            self.config.save()
            dialog.destroy()

        except Exception:
            pass

    def _on_exit(self):
        """退出应用。"""
        log.info("Application exiting")
        self.engine.stop()
        self._cleanup()
        self._root.quit()
        self._root.destroy()

    def _cleanup(self):
        """清理资源 — 移除托盘图标。"""
        if self._tray_added and self._hwnd:
            try:
                shell32.Shell_NotifyIconW(NIM_DELETE, byref(self._nid))
            except Exception:
                pass
            self._tray_added = False


# =============================================================================
# 主入口
# =============================================================================

def main():
    """应用程序主入口。"""
    # 设置工作目录
    try:
        script_dir = Path(sys.argv[0]).parent.resolve()
        os.chdir(script_dir)
    except Exception:
        pass

    log.info("Window Switcher starting (PID=%d)", os.getpid())

    # 确保 tkinter 根窗口在 Windows DPI 感知下正常
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        pass

    # 互斥锁检测：防止重复运行
    ERROR_ALREADY_EXISTS = 183
    mutex_name = "Global\\WindowSwitcher_SingleInstance_Mutex"
    mutex = kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        # 已有实例在运行，弹窗提示并退出
        import tkinter.messagebox as mb
        root = tk.Tk()
        root.withdraw()
        mb.showinfo(
            "Window Switcher",
            "Window Switcher is already running.\n\n"
            "Check the system tray (bottom-right corner)\n"
            "for the switcher icon."
        )
        root.destroy()
        sys.exit(0)

    app = TrayApp()
    app.run()


if __name__ == "__main__":
    main()
