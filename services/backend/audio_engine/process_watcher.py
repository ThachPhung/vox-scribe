"""Phát hiện Zoom, Teams hoặc Google Meet đang mở và phát sự kiện mở/đóng.

Zoom/Teams nhận theo tên tiến trình (psutil). Google Meet chạy trong trình duyệt nên
nhận theo tiêu đề cửa sổ (xem window_titles). Desktop dùng sự kiện để hiện thông báo
khi người dùng bắt đầu một cuộc họp.
"""

from __future__ import annotations

import argparse
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

import psutil

from .window_titles import find_open_meet_calls

AppName = Literal["zoom", "teams", "meet"]

KNOWN_APPS: dict[str, tuple[str, ...]] = {
    "zoom": ("zoom.exe",),
    "teams": ("ms-teams.exe", "teams.exe"),
}
MEET_APP = "meet"


def _list_processes() -> list[tuple[int, str]]:
    return [(p.info["pid"], p.info["name"] or "") for p in psutil.process_iter(["pid", "name"])]


@dataclass(frozen=True)
class AppEvent:
    """Một lần Zoom/Teams/Meet mở vào hoặc đóng đi."""

    app: str
    running: bool
    pids: tuple[int, ...] = ()


class ProcessWatcher:
    """Theo dõi Zoom/Teams/Meet, chỉ trả về sự kiện khi có thay đổi.

    Quét tiến trình theo chu kỳ trên một thread nền:

        watcher = ProcessWatcher()
        watcher.start(lambda e: print(e.app, "opened" if e.running else "closed"))
        ...
        watcher.stop()
    """

    def __init__(
        self,
        *,
        interval_sec: float = 2.0,
        process_lister: Callable[[], Iterable[tuple[int, str]]] = _list_processes,
        meet_finder: Callable[[], tuple[int, ...]] = find_open_meet_calls,
    ) -> None:
        self.interval_sec = interval_sec
        self._names = {app: {n.lower() for n in names} for app, names in KNOWN_APPS.items()}
        self._list_processes = process_lister
        self._find_meet = meet_finder
        self._baseline: dict[str, tuple[int, ...]] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def scan(self) -> dict[str, tuple[int, ...]]:
        """Tên app -> pid đang chạy (tên tiến trình không phân biệt hoa thường)."""
        found: dict[str, list[int]] = {app: [] for app in self._names}
        for pid, raw_name in self._list_processes():
            name = raw_name.lower()
            for app, names in self._names.items():
                if name in names:
                    found[app].append(pid)
        result = {app: tuple(sorted(pids)) for app, pids in found.items()}
        return {**result, MEET_APP: self._find_meet()}

    def poll(self) -> list[AppEvent]:
        """So sánh với lần quét trước; lần đầu chỉ đặt mốc, không báo sự kiện."""
        current = self.scan()
        if not self._baseline:
            self._baseline = current
            return []
        events = [
            AppEvent(app=app, running=bool(pids), pids=pids)
            for app, pids in current.items()
            if bool(pids) != bool(self._baseline[app])
        ]
        self._baseline = current
        return events

    def start(self, on_event: Callable[[AppEvent], None]) -> None:
        """Chạy quét nền; `on_event` gọi trên thread watcher, không block thread nào khác."""
        if self._thread is not None:
            raise RuntimeError("ProcessWatcher is already running")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, args=(on_event,), name="process-watcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=self.interval_sec + 1)
        self._thread = None

    def _loop(self, on_event: Callable[[AppEvent], None]) -> None:
        while not self._stop_event.wait(self.interval_sec):
            for event in self.poll():
                on_event(event)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m audio_engine.process_watcher",
        description="In ra khi Zoom/Teams/Meet mở hoặc đóng (Ctrl+C để dừng).",
    )
    parser.add_argument("-i", "--interval", type=float, default=2.0, help="giây giữa hai lần quét")
    args = parser.parse_args(argv)

    def show(event: AppEvent) -> None:
        state = f"mở (pid {', '.join(map(str, event.pids))})" if event.running else "đóng"
        print(f"{event.app}: {state}")

    watcher = ProcessWatcher(interval_sec=args.interval)
    print(f"Quét Zoom/Teams/Meet mỗi {args.interval:g} s. Ctrl+C để dừng.")
    try:
        watcher.start(show)
        threading.Event().wait()
    except KeyboardInterrupt:
        watcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
