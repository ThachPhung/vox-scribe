"""Thu âm thanh hệ thống (Zoom/Meet/Teams) qua WASAPI Loopback (kênh phải của file stereo)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .capture import InputRecorder
from .device_manager import default_speaker, loopback_for
from .models import AudioDevice

if TYPE_CHECKING:
    import pyaudiowpatch as pyaudio


class LoopbackRecorder(InputRecorder):
    """Captures what a speaker plays through its WASAPI loopback endpoint.

    No virtual audio cable is needed. Windows delivers no data while nothing is
    playing; StereoRecorder fills those gaps with silence.
    """

    def __init__(
        self,
        pa: pyaudio.PyAudio,
        speaker: AudioDevice | None = None,
        *,
        frames_per_buffer: int = 1024,
    ) -> None:
        self.speaker = speaker or default_speaker(pa)
        super().__init__(pa, loopback_for(pa, self.speaker), frames_per_buffer=frames_per_buffer)
