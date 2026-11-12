"""Nối API ghi âm với audio_engine: mở mic + loopback, ghi WAV, đẩy đồng hồ và sóng âm.

Mỗi lần chỉ ghi một cuộc họp. Trong lúc ghi, một thread nền gửi `recording.waveform`
mỗi nhịp và `recording.status` (thời gian đã ghi) mỗi STATUS_EVERY nhịp.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from core_app.api.websocket import (
    RecordingStatusData,
    RecordingStatusEvent,
    WaveformData,
    WaveformEvent,
    WsEvent,
)

logger = logging.getLogger("voxscribe.recording")

TICK_SEC = 0.1
STATUS_EVERY = 5  # gửi đồng hồ mỗi 0,5 s


class Recorder(Protocol):
    elapsed_sec: float
    levels: tuple[float, float]

    def start(self) -> None: ...

    def stop(self) -> tuple[str, float]:
        """Dừng ghi, trả về (đường dẫn file, thời lượng giây)."""
        ...


class AudioEngineRecorder:
    """Recorder thật: mic Windows mặc định (trái) + loa mặc định qua loopback (phải)."""

    def __init__(self, output_path: Path) -> None:
        import pyaudiowpatch as pyaudio

        from audio_engine.loopback_recorder import LoopbackRecorder
        from audio_engine.mic_recorder import MicRecorder
        from audio_engine.stereo_mixer import StereoRecorder

        self._pa = pyaudio.PyAudio()
        try:
            self._stereo = StereoRecorder(MicRecorder(self._pa), LoopbackRecorder(self._pa), output_path)
        except BaseException:
            self._pa.terminate()
            raise

    @property
    def elapsed_sec(self) -> float:
        return self._stereo.elapsed_sec

    @property
    def levels(self) -> tuple[float, float]:
        return self._stereo.levels

    def start(self) -> None:
        try:
            self._stereo.start()
        except BaseException:
            self._pa.terminate()
            raise

    def stop(self) -> tuple[str, float]:
        try:
            result = self._stereo.stop()
        finally:
            self._pa.terminate()
        return result.file_path, result.duration_sec


class _Active:
    def __init__(self, meeting_id: str, recorder: Recorder) -> None:
        self.meeting_id = meeting_id
        self.recorder = recorder
        self.stop_event = threading.Event()
        self.ticker: threading.Thread | None = None


class RecordingSessions:
    def __init__(
        self,
        recordings_dir: Path,
        *,
        publish: Callable[[WsEvent], None],
        recorder_factory: Callable[[Path], Recorder] = AudioEngineRecorder,
        tick_sec: float = TICK_SEC,
    ) -> None:
        self.recordings_dir = recordings_dir
        self._publish = publish
        self._factory = recorder_factory
        self._tick_sec = tick_sec
        self._lock = threading.Lock()
        self._active: _Active | None = None

    def set_publisher(self, publish: Callable[[WsEvent], None]) -> None:
        self._publish = publish

    def is_recording(self, meeting_id: str) -> bool:
        active = self._active
        return active is not None and active.meeting_id == meeting_id

    def start(self, meeting_id: str) -> None:
        """Bắt đầu ghi; lỗi thiết bị âm thanh được ném ra cho route xử lý."""
        with self._lock:
            if self._active is not None:
                raise RuntimeError(f"Đang ghi cuộc họp {self._active.meeting_id}")
            self.recordings_dir.mkdir(parents=True, exist_ok=True)
            recorder = self._factory(self.recordings_dir / f"{meeting_id}.wav")
            recorder.start()
            active = _Active(meeting_id, recorder)
            active.ticker = threading.Thread(
                target=self._tick, args=(active,), name="recording-ticker", daemon=True
            )
            self._active = active
            active.ticker.start()

    def stop(self, meeting_id: str) -> tuple[str, float]:
        with self._lock:
            active = self._active
            if active is None or active.meeting_id != meeting_id:
                raise RuntimeError(f"Không có bản ghi đang chạy cho {meeting_id}")
            self._active = None
        active.stop_event.set()
        if active.ticker is not None:
            active.ticker.join(timeout=1)
        return active.recorder.stop()

    def stop_all(self) -> None:
        active = self._active
        if active is None:
            return
        try:
            self.stop(active.meeting_id)
        except Exception:
            logger.exception("Không dừng được bản ghi %s khi tắt server", active.meeting_id)

    def _tick(self, active: _Active) -> None:
        count = 0
        while not active.stop_event.wait(self._tick_sec):
            recorder = active.recorder
            left, right = recorder.levels
            try:
                self._publish(WaveformEvent(meeting_id=active.meeting_id, data=WaveformData(left=left, right=right)))
                if count % STATUS_EVERY == 0:
                    status = RecordingStatusData(state="recording", elapsed_sec=recorder.elapsed_sec)
                    self._publish(RecordingStatusEvent(meeting_id=active.meeting_id, data=status))
            except Exception:
                logger.exception("Không gửi được sự kiện ghi âm")
            count += 1
