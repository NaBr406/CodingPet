from __future__ import annotations

import base64
import ctypes
import io
import logging
import os
import shutil
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from threading import Event

from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal

from config_loader import AppConfig
from llm_client import analyze_redacted_observation, analyze_screenshot
from logging_utils import LOGGER_NAME


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_NAME_BUFFER_SIZE = 32768

try:
    import pygetwindow as gw
except Exception:
    gw = None

try:
    from mss import mss
except Exception:
    mss = None


@dataclass(frozen=True)
class ActiveWindowInfo:
    title: str = ""
    process_name: str = ""
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0


class ObserverWorker(QThread):
    # 后台观察线程：定时观察前台窗口，隐私进程会降级成只发送进程名。
    observation_started = pyqtSignal(object)
    observation_failed = pyqtSignal(object)
    observation_ready = pyqtSignal(object, str, str, str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._stop_requested = Event()
        self._observation_allowed = Event()
        self._observation_allowed.set()
        self._interval_ms = config.observer.interval_seconds * 1000

    def stop(self) -> None:
        # 通过标志位协作退出，而不是强杀线程，避免截图请求卡在半路时留下脏状态。
        self._stop_requested.set()
        self._observation_allowed.clear()

    def set_observation_allowed(self, allowed: bool) -> None:
        # 这个开关由主线程维护，worker 只读它，避免忙碌时还去截图和调模型。
        if allowed and not self._stop_requested.is_set():
            self._observation_allowed.set()
        else:
            self._observation_allowed.clear()

    def is_stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def run(self) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        logger.info("阶段 3 成功：观察线程已就绪。")

        try:
            with mss() as screen_capture:
                while not self._stop_requested.is_set():
                    if not self._observation_allowed.is_set():
                        logger.info("观察线程跳过本轮：当前用户交互或请求正忙。")
                        self._sleep_interruptibly(self._interval_ms)
                        continue

                    try:
                        # 每轮先观测一次，再进入等待；这样启动后不会白白空转一个间隔。
                        self._observe_once(screen_capture)
                    except Exception:
                        logger.warning("观察循环失败，已回退到 IDLE。", exc_info=True)
                        self.observation_failed.emit(self)
                    self._sleep_interruptibly(self._interval_ms)
        except Exception:
            logger.warning("观察线程初始化截图环境失败，已停用本轮观察。", exc_info=True)
            self.observation_failed.emit(self)

    def _observe_once(self, screen_capture: mss) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        active_window = _get_active_window_info()
        process_name = active_window.process_name

        if _is_privacy_process(process_name, self._config.observer.privacy_process_names):
            if self._stop_requested.is_set() or not self._observation_allowed.is_set():
                return

            # 隐私窗口不传标题、不截图，只把进程名交给模型做脱敏观察。
            self.observation_started.emit(self)
            if self._stop_requested.is_set() or not self._observation_allowed.is_set():
                return

            logger.info("观察线程命中隐私进程，仅发送进程名：%s", process_name)
            reply = analyze_redacted_observation(self._config, process_name)
            if self._stop_requested.is_set() or not self._observation_allowed.is_set():
                return

            logger.info("观察线程已为隐私进程生成脱敏主动评论：%s", process_name)
            self.observation_ready.emit(self, process_name, reply.message, reply.emotion.value)
            return

        title = active_window.title or "未识别前台窗口"

        if self._stop_requested.is_set() or not self._observation_allowed.is_set():
            return

        # 先告诉主界面“现在要观察了”，这样 UI 可以切到 REVIEWING 态。
        self.observation_started.emit(self)
        if self._stop_requested.is_set() or not self._observation_allowed.is_set():
            return

        logger.info("观察线程准备截图并请求视觉模型：%s", title)
        screenshot_base64 = self._capture_active_region(screen_capture, active_window)
        if self._stop_requested.is_set() or not self._observation_allowed.is_set():
            return

        reply = analyze_screenshot(self._config, screenshot_base64, title)
        if self._stop_requested.is_set() or not self._observation_allowed.is_set():
            return

        logger.info("观察线程已为窗口生成主动评论：%s", title)
        self.observation_ready.emit(self, title, reply.message, reply.emotion.value)

    def _capture_active_region(self, screen_capture: mss, active_window: object | None) -> str:
        # 优先只截前台窗口区域；如果取不到窗口几何，再退回整屏。
        region = self._resolve_region(screen_capture, active_window)
        screenshot = screen_capture.grab(region)

        # 一样先压缩尺寸再编码，减少模型请求和本地内存压力。
        image = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        image.thumbnail((1600, 900), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _resolve_region(self, screen_capture: mss, active_window: object | None) -> dict[str, int]:
        # 某些窗口句柄拿不到坐标或大小时，直接回退为整屏，保证观察链路不断。
        left = int(getattr(active_window, "left", 0) or 0)
        top = int(getattr(active_window, "top", 0) or 0)
        width = int(getattr(active_window, "width", 0) or 0)
        height = int(getattr(active_window, "height", 0) or 0)

        if width > 0 and height > 0:
            return {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }

        return dict(screen_capture.monitors[1])

    def _sleep_interruptibly(self, total_ms: int) -> None:
        # 分块睡眠，便于 stop() 尽快生效，而不是一口气睡满整个间隔。
        remaining = total_ms
        while not self._stop_requested.is_set() and remaining > 0:
            chunk = min(500, remaining)
            self.msleep(chunk)
            remaining -= chunk


def _get_active_window_info() -> ActiveWindowInfo:
    if sys.platform.startswith("linux"):
        linux_window = _get_linux_active_window_info()
        if linux_window.title or linux_window.process_name:
            return linux_window

    return _get_pygetwindow_active_window_info()


def _get_pygetwindow_active_window_info() -> ActiveWindowInfo:
    process_name = _get_foreground_process_name()
    if gw is None:
        return ActiveWindowInfo(process_name=process_name)

    try:
        active_window = gw.getActiveWindow()
        title = ""
        if active_window is not None:
            title = str(getattr(active_window, "title", "") or "")
        if not title:
            title = str(gw.getActiveWindowTitle() or "")

        return ActiveWindowInfo(
            title=title,
            process_name=process_name,
            left=int(getattr(active_window, "left", 0) or 0),
            top=int(getattr(active_window, "top", 0) or 0),
            width=int(getattr(active_window, "width", 0) or 0),
            height=int(getattr(active_window, "height", 0) or 0),
        )
    except Exception:
        logging.getLogger(LOGGER_NAME).debug("读取前台窗口信息失败。", exc_info=True)
        return ActiveWindowInfo(process_name=process_name)


def _get_linux_active_window_info() -> ActiveWindowInfo:
    if not os.environ.get("DISPLAY") or shutil.which("xdotool") is None:
        return ActiveWindowInfo()

    window_id = _run_command_text(["xdotool", "getactivewindow"])
    if not window_id:
        return ActiveWindowInfo()

    title = _run_command_text(["xdotool", "getwindowname", window_id])
    process_name = _linux_process_name(_run_command_text(["xdotool", "getwindowpid", window_id]))
    geometry = _parse_xdotool_geometry(
        _run_command_text(["xdotool", "getwindowgeometry", "--shell", window_id])
    )

    return ActiveWindowInfo(
        title=title,
        process_name=process_name,
        left=geometry.get("X", 0),
        top=geometry.get("Y", 0),
        width=geometry.get("WIDTH", 0),
        height=geometry.get("HEIGHT", 0),
    )


def _run_command_text(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""

    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _linux_process_name(pid_text: str) -> str:
    try:
        pid = int(pid_text.strip())
    except ValueError:
        return ""

    comm_path = Path("/proc") / str(pid) / "comm"
    try:
        return comm_path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def _parse_xdotool_geometry(output: str) -> dict[str, int]:
    geometry: dict[str, int] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"X", "Y", "WIDTH", "HEIGHT"}:
            try:
                geometry[key] = int(value)
            except ValueError:
                continue
    return geometry


def _get_foreground_process_name() -> str:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return ""

    try:
        user32 = windll.user32
        kernel32 = windll.kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        )
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""

        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if not process_id.value:
            return ""

        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            process_id.value,
        )
        if not handle:
            return ""

        try:
            size = wintypes.DWORD(PROCESS_NAME_BUFFER_SIZE)
            buffer = ctypes.create_unicode_buffer(size.value)
            ok = kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(size),
            )
            if not ok:
                return ""
            return PureWindowsPath(buffer.value).name
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        logging.getLogger(LOGGER_NAME).debug("读取前台进程名失败。", exc_info=True)
        return ""


def _is_privacy_process(process_name: str, configured_names: tuple[str, ...]) -> bool:
    process_tokens = _process_name_tokens(process_name)
    if not process_tokens:
        return False

    for configured_name in configured_names:
        if process_tokens & _process_name_tokens(configured_name):
            return True
    return False


def _process_name_tokens(process_name: str) -> set[str]:
    normalized = process_name.strip().lower()
    if not normalized:
        return set()

    stem = normalized[:-4] if normalized.endswith(".exe") else normalized
    return {normalized, stem}
