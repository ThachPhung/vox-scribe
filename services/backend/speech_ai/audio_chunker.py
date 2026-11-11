"""Cắt file âm thanh dài thành từng đoạn chuẩn 16kHz.

- `load_audio`: đọc mọi định dạng (wav/mp3/m4a...) qua ffmpeg -> float32 mono 16kHz.
  Với file stereo của audio_engine (Trái = Mic, Phải = Loa), có thể lấy riêng 1 kênh.
- `VadSegmenter`: dùng Silero VAD (ONNX, qua sherpa-onnx) cắt bỏ khoảng lặng, trả về
  các đoạn có tiếng nói kèm offset trên timeline gốc.
- `split_fixed`: cắt cứng theo độ dài (dự phòng khi không có VAD).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Literal

import numpy as np

SAMPLE_RATE = 16_000
Channel = Literal["mix", "left", "right"]


def load_audio(path: str, channel: Channel = "mix", sr: int = SAMPLE_RATE) -> np.ndarray:
    """Đọc file âm thanh thành float32 mono ở `sr` Hz.

    channel: "mix" trộn mọi kênh | "left" chỉ Mic | "right" chỉ Loa/Loopback
    """
    af = {"mix": None, "left": "pan=mono|c0=c0", "right": "pan=mono|c0=c1"}[channel]
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", path]
    if af:
        cmd += ["-af", af]
    cmd += ["-ac", "1", "-ar", str(sr), "-f", "s16le", "-acodec", "pcm_s16le", "-"]
    try:
        raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    except FileNotFoundError as e:
        raise RuntimeError("Không tìm thấy ffmpeg trong PATH") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg lỗi khi đọc {path}: {e.stderr.decode(errors='ignore')}") from e
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


@dataclass
class AudioChunk:
    start: float  # giây, trên timeline gốc
    audio: np.ndarray

    @property
    def end(self) -> float:
        return self.start + len(self.audio) / SAMPLE_RATE


def split_fixed(audio: np.ndarray, offset: float = 0.0, max_sec: float = 20.0) -> list[AudioChunk]:
    size = int(max_sec * SAMPLE_RATE)
    return [
        AudioChunk(offset + i / SAMPLE_RATE, audio[i : i + size])
        for i in range(0, len(audio), size)
        if len(audio[i : i + size]) > 0
    ]


class VadSegmenter:
    """Silero VAD: tách các đoạn có tiếng nói, mỗi đoạn dài tối đa `max_speech_sec`."""

    def __init__(
        self,
        model_path: str,
        threshold: float = 0.5,
        min_silence_sec: float = 0.3,
        min_speech_sec: float = 0.25,
        max_speech_sec: float = 20.0,
        num_threads: int = 1,
    ):
        import sherpa_onnx

        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = model_path
        cfg.silero_vad.threshold = threshold
        cfg.silero_vad.min_silence_duration = min_silence_sec
        cfg.silero_vad.min_speech_duration = min_speech_sec
        cfg.silero_vad.max_speech_duration = max_speech_sec
        cfg.sample_rate = SAMPLE_RATE
        cfg.num_threads = num_threads
        self._cfg = cfg
        self._window = cfg.silero_vad.window_size
        self._sherpa = sherpa_onnx

    def segment(self, audio: np.ndarray, offset: float = 0.0) -> list[AudioChunk]:
        vad = self._sherpa.VoiceActivityDetector(
            self._cfg, buffer_size_in_seconds=len(audio) / SAMPLE_RATE + 1
        )
        out: list[AudioChunk] = []

        def drain() -> None:
            while not vad.empty():
                seg = vad.front
                out.append(AudioChunk(offset + seg.start / SAMPLE_RATE, np.asarray(seg.samples, np.float32)))
                vad.pop()

        for i in range(0, len(audio), self._window):
            vad.accept_waveform(audio[i : i + self._window])
            drain()
        vad.flush()
        drain()
        return out
