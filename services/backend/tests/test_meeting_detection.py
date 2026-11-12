"""Nhận diện Google Meet theo tiêu đề cửa sổ trình duyệt và sự kiện của ProcessWatcher."""

from audio_engine.process_watcher import AppEvent, ProcessWatcher
from audio_engine.window_titles import BrowserWindow, find_meet_pids, is_meet_call_title


def test_meet_call_title_with_meeting_code_is_detected():
    assert is_meet_call_title("Meet - abc-defg-hij - Google Chrome")
    assert is_meet_call_title("Meet – xyz-abcd-efg và 1 trang khác - Cá nhân - Microsoft Edge")
    assert is_meet_call_title("Meet - abc-defg-hij")  # cửa sổ PWA Meet


def test_meet_landing_page_and_other_tabs_are_ignored():
    assert not is_meet_call_title("Google Meet - Google Chrome")
    assert not is_meet_call_title("(60) podcast tiếng việt - YouTube - Brave")
    assert not is_meet_call_title("Meeting notes abc-defg-hij - Google Docs")


def test_find_meet_pids_keeps_only_browsers_with_a_meet_call():
    windows = [
        BrowserWindow(pid=10, process="brave.exe", title="Meet - abc-defg-hij - Brave"),
        BrowserWindow(pid=11, process="chrome.exe", title="Gmail - Google Chrome"),
        BrowserWindow(pid=12, process="notepad.exe", title="Meet - abc-defg-hij.txt"),
    ]
    assert find_meet_pids(windows) == (10,)


def _watcher(process_names: list[tuple[int, str]], meet_pids: tuple[int, ...]) -> ProcessWatcher:
    return ProcessWatcher(process_lister=lambda: process_names, meet_finder=lambda: meet_pids)


def test_watcher_reports_meet_opening_and_closing():
    state = {"meet": ()}
    watcher = ProcessWatcher(process_lister=lambda: [], meet_finder=lambda: state["meet"])

    assert watcher.poll() == []  # lần đầu chỉ đặt mốc
    state["meet"] = (42,)
    assert watcher.poll() == [AppEvent(app="meet", running=True, pids=(42,))]
    state["meet"] = ()
    assert watcher.poll() == [AppEvent(app="meet", running=False, pids=())]


def test_watcher_still_detects_zoom_and_teams_by_process_name():
    watcher = _watcher([(1, "Zoom.exe"), (2, "ms-teams.exe"), (3, "explorer.exe")], ())
    assert watcher.scan() == {"zoom": (1,), "teams": (2,), "meet": ()}
