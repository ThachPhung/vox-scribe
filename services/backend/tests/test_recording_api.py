"""API ghi âm gọi audio_engine qua RecordingSessions và đẩy đồng hồ, sóng âm lên WebSocket."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core_app.api.dependencies import Services
from core_app.api.websocket import EventHub
from core_app.llm_agent.summarizer import ReportGenerationSlots
from core_app.recording.session import RecordingSessions
from main import create_app


class FakeRecorder:
    """Thay StereoRecorder: ghi một file rỗng, báo mức âm cố định."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.started = False
        self.stopped = False
        self.levels = (0.5, 0.25)
        self.elapsed_sec = 3.0

    def start(self) -> None:
        self.started = True

    def stop(self) -> tuple[str, float]:
        self.stopped = True
        self.output_path.write_bytes(b"RIFF")
        return str(self.output_path), 3.0


class FailingRecorder(FakeRecorder):
    def start(self) -> None:
        raise OSError("không mở được mic")


def _sessions(tmp_path: Path, factory, events: list) -> RecordingSessions:
    return RecordingSessions(
        tmp_path / "recordings", publish=events.append, recorder_factory=factory, tick_sec=0.01
    )


def test_session_publishes_clock_and_waveform_while_recording(tmp_path: Path):
    events: list = []
    recorders: list[FakeRecorder] = []

    def factory(path: Path) -> FakeRecorder:
        recorders.append(FakeRecorder(path))
        return recorders[-1]

    sessions = _sessions(tmp_path, factory, events)
    sessions.start("m1")
    got_both = threading.Event()
    for _ in range(200):
        types = {e.type for e in events}
        if {"recording.status", "recording.waveform"} <= types:
            got_both.set()
            break
        threading.Event().wait(0.01)
    path, duration = sessions.stop("m1")

    assert got_both.is_set()
    status = next(e for e in events if e.type == "recording.status")
    assert status.data.state == "recording" and status.data.elapsed_sec == 3.0
    wave = next(e for e in events if e.type == "recording.waveform")
    assert (wave.data.left, wave.data.right) == (0.5, 0.25)
    assert recorders[0].stopped and Path(path).name == "m1.wav" and duration == 3.0


def test_only_one_recording_at_a_time(tmp_path: Path):
    sessions = _sessions(tmp_path, FakeRecorder, [])
    sessions.start("m1")
    with pytest.raises(RuntimeError):
        sessions.start("m2")
    sessions.stop("m1")


@pytest.fixture
def client_factory(tmp_path: Path):
    def make(factory) -> TestClient:
        def services() -> Services:
            return Services(
                db_path=tmp_path / "test.db",
                report_generator=None,
                report_slots=ReportGenerationSlots(1),
                event_hub=EventHub(),
                recordings=RecordingSessions(
                    tmp_path / "recordings", publish=lambda _e: None, recorder_factory=factory
                ),
                start_watcher=False,
            )

        return TestClient(create_app(services))

    return make


def test_start_and_stop_saves_audio_path(client_factory):
    with client_factory(FakeRecorder) as client:
        meeting = client.post("/recording/start", json={"title": "Họp", "capture_mode": "headset"}).json()
        stopped = client.post(f"/recording/{meeting['id']}/stop")

    assert stopped.status_code == 200
    body = stopped.json()
    assert body["audio_path"].endswith(f"{meeting['id']}.wav")
    assert body["duration_sec"] == 3.0


def test_start_reports_device_error_and_does_not_leave_meeting_recording(client_factory):
    with client_factory(FailingRecorder) as client:
        response = client.post("/recording/start", json={"title": "Họp", "capture_mode": "room"})
        meetings = client.get("/meetings").json()

    assert response.status_code == 503
    assert "không mở được mic" in response.json()["detail"]
    assert all(m["status"] != "recording" for m in meetings)
