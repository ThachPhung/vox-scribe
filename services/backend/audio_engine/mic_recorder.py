"""Thu âm thanh từ microphone (kênh trái của file stereo)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .capture import InputRecorder
from .device_manager import default_microphone
from .models import AudioDevice

if TYPE_CHECKING:
    import pyaudiowpatch as pyaudio


class MicRecorder(InputRecorder):
    """Captures a WASAPI microphone; uses the Windows default when none is given."""

    def __init__(
        self,
        pa: pyaudio.PyAudio,
        device: AudioDevice | None = None,
        *,
        frames_per_buffer: int = 1024,
    ) -> None:
        device = device or default_microphone(pa)
        if device.is_loopback:
            raise ValueError(f"{device.name!r} is a loopback device, not a microphone")
        super().__init__(pa, device, frames_per_buffer=frames_per_buffer)
