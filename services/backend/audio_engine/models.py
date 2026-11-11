"""Kiểu dữ liệu dùng chung của audio_engine (không phụ thuộc thư viện thu âm)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np


@dataclass(frozen=True)
class AudioDevice:
    """A WASAPI endpoint as reported by PortAudio."""

    index: int
    name: str
    channels: int
    sample_rate: int
    is_loopback: bool = False


@dataclass(frozen=True)
class AudioChunk:
    """One block of captured audio.

    samples: mono float32 at the source's native sample rate.
    captured_at: time.perf_counter() when the block arrived (after its last sample).
    """

    samples: np.ndarray
    captured_at: float


@dataclass(frozen=True)
class ChannelStats:
    """How much one channel had to be corrected to stay on the shared timeline."""

    padded_sec: float
    dropped_sec: float
    overflows: int


@dataclass(frozen=True)
class RecordingResult:
    """Outcome of one recording session."""

    meeting_id: str
    file_path: str
    sample_rate: int
    channels: int
    started_at: datetime
    duration_sec: float
    mic: ChannelStats
    loopback: ChannelStats

    def to_contract(self) -> dict[str, Any]:
        """Payload matching shared/schemas/audio_contract.json."""
        return {
            "meeting_id": self.meeting_id,
            "file_path": self.file_path,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "started_at": self.started_at.isoformat(),
            "duration_sec": round(self.duration_sec, 3),
        }
