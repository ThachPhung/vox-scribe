"""Cắt file âm thanh dài thành từng đoạn chuẩn 16kHz.

- `load_audio`: đọc mọi định dạng (wav/mp3/m4a...) qua ffmpeg -> float32 mono 16kHz.
  Với file stereo của audio_engine (Trái = Mic, Phải = Loa), có thể chọn lấy riêng 1 kênh.
- `chunk_audio`: chia mảng âm thanh thành các đoạn có chồng lấn, giữ offset để
  ghép timestamp về lại timeline gốc.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Iterator, Literal

import numpy as np

SAMPLE_RATE = 16_000
Channel = Literal["mix", "left", "right"]


def load_audio(path: str, channel: Channel = "mix", sr: int = SAMPLE_RATE) -> np.ndarray:
    """Đọc file âm thanh thành float32 mono ở `sr` Hz.

    channel:
        "mix"   – trộn tất cả kênh (mặc định)
        "left"  – chỉ kênh Trái (Mic)
        "right" – chỉ kênh Phải (Loa/Loopback)
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
    index: int
    offset_sec: float  # vị trí bắt đầu của đoạn trên timeline gốc
    audio: np.ndarray

    @property
    def duration_sec(self) -> float:
        return len(self.audio) / SAMPLE_RATE


def chunk_audio(
    audio: np.ndarray,
    chunk_sec: float = 30.0,
    overlap_sec: float = 1.0,
    sr: int = SAMPLE_RATE,
) -> Iterator[AudioChunk]:
    """Chia audio thành các đoạn `chunk_sec` giây, chồng lấn `overlap_sec` giây."""
    if overlap_sec >= chunk_sec:
        raise ValueError("overlap_sec phải nhỏ hơn chunk_sec")
    size = int(chunk_sec * sr)
    step = int((chunk_sec - overlap_sec) * sr)
    for i, start in enumerate(range(0, max(len(audio), 1), step)):
        piece = audio[start : start + size]
        if len(piece) == 0:
            break
        yield AudioChunk(index=i, offset_sec=start / sr, audio=piece)
        if start + size >= len(audio):
            break
