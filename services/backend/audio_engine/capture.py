"""Luồng thu WASAPI dùng chung cho mic và loopback."""

from __future__ import annotations

import queue
import time
from typing import Any

import numpy as np
import pyaudiowpatch as pyaudio

from .models import AudioChunk, AudioDevice


class InputRecorder:
    """Opens one WASAPI input stream and queues timestamped mono chunks.

    Audio is captured at the device's native rate and channel count (required in
    WASAPI shared mode) and downmixed to mono float32. Resampling and alignment
    happen later in StereoRecorder.
    """

    def __init__(
        self,
        pa: pyaudio.PyAudio,
        device: AudioDevice,
        *,
        frames_per_buffer: int = 1024,
    ) -> None:
        self.device = device
        self.overflows = 0
        self._pa = pa
        self._frames_per_buffer = frames_per_buffer
        self._queue: queue.SimpleQueue[AudioChunk] = queue.SimpleQueue()
        self._stream: Any = None

    @property
    def sample_rate(self) -> int:
        return self.device.sample_rate

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError(f"{self.device.name!r} is already recording")
        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self.device.channels,
            rate=self.device.sample_rate,
            input=True,
            input_device_index=self.device.index,
            frames_per_buffer=self._frames_per_buffer,
            stream_callback=self._on_audio,
        )

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop_stream()
        self._stream.close()
        self._stream = None

    def drain(self) -> list[AudioChunk]:
        """Return every chunk captured since the previous call."""
        chunks: list[AudioChunk] = []
        while True:
            try:
                chunks.append(self._queue.get_nowait())
            except queue.Empty:
                return chunks

    def _on_audio(
        self, in_data: bytes, frame_count: int, time_info: dict, status: int
    ) -> tuple[None, int]:
        # Runs on PortAudio's thread: keep it short and never block.
        captured_at = time.perf_counter()
        frames = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self.device.channels)
        self._queue.put(AudioChunk(frames.mean(axis=1, dtype=np.float32), captured_at))
        if status & pyaudio.paInputOverflow:
            self.overflows += 1
        return None, pyaudio.paContinue
