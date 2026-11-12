"""Tìm cuộc họp Google Meet đang mở qua tiêu đề cửa sổ trình duyệt (Windows).

Meet chạy trong trình duyệt nên không có tiến trình riêng. Trình duyệt đặt tiêu đề cửa sổ
theo tab đang chọn, và khi đang trong cuộc họp tab có tiêu đề "Meet - abc-defg-hij". Vì vậy
chỉ thấy được cuộc họp khi tab Meet là tab đang chọn của một cửa sổ (hoặc Meet mở dạng app).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass

import psutil

BROWSER_PROCESSES = frozenset(
    {"chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe", "browser.exe"}
)
# Mã cuộc họp Meet: 3-4-3 chữ thường, đứng sau chữ "Meet" và dấu gạch.
_MEET_CALL_TITLE = re.compile(r"^Meet\s*[-–—]\s*[a-z]{3}-[a-z]{4}-[a-z]{3}\b")


@dataclass(frozen=True)
class BrowserWindow:
    pid: int
    process: str
    title: str


def is_meet_call_title(title: str) -> bool:
    """Đúng khi tiêu đề là tab đang trong cuộc họp Meet (không tính trang chủ Google Meet)."""
    return _MEET_CALL_TITLE.match(title.strip()) is not None


def find_meet_pids(windows: Iterable[BrowserWindow]) -> tuple[int, ...]:
    """Pid của các trình duyệt đang hiện một cuộc họp Meet."""
    return tuple(
        sorted(
            {w.pid for w in windows if w.process.lower() in BROWSER_PROCESSES and is_meet_call_title(w.title)}
        )
    )


def list_visible_windows() -> list[BrowserWindow]:
    """Mọi cửa sổ đang hiện có tiêu đề, kèm tên tiến trình. Ngoài Windows trả về rỗng."""
    if sys.platform != "win32":
        return []
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    windows: list[BrowserWindow] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def on_window(hwnd: int, _param: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            name = psutil.Process(pid.value).name()
        except psutil.Error:
            return True
        windows.append(BrowserWindow(pid=pid.value, process=name, title=buffer.value))
        return True

    user32.EnumWindows(on_window, 0)
    return windows


def find_open_meet_calls() -> tuple[int, ...]:
    return find_meet_pids(list_visible_windows())
