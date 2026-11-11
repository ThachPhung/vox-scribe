"""Chạy pyannote tách các giọng nói (SPEAKER_00, 01...).

Yêu cầu:
- Hugging Face token (biến môi trường HF_TOKEN, hoặc đã `huggingface-cli login`).
- Đã bấm "Agree" điều khoản trên HF cho các model:
    https://huggingface.co/pyannote/speaker-diarization-3.1
    https://huggingface.co/pyannote/segmentation-3.0
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from .audio_chunker import SAMPLE_RATE

DEFAULT_PIPELINE = "pyannote/speaker-diarization-3.1"


@dataclass
class DiarizerConfig:
    pipeline: str = DEFAULT_PIPELINE
    device: str = "cpu"  # cpu | cuda | mps
    num_speakers: int | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    hf_token: str | None = None


@dataclass
class Turn:
    start: float
    end: float
    speaker: str


class Diarizer:
    def __init__(self, cfg: DiarizerConfig | None = None):
        import torch
        from pyannote.audio import Pipeline

        self.cfg = cfg or DiarizerConfig()
        token = self.cfg.hf_token or os.getenv("HF_TOKEN")  # None -> dùng token đã login
        try:
            self.pipeline = Pipeline.from_pretrained(self.cfg.pipeline, use_auth_token=token)
        except TypeError:  # pyannote >= 4 đổi tên tham số
            self.pipeline = Pipeline.from_pretrained(self.cfg.pipeline, token=token)
        if self.pipeline is None:
            raise RuntimeError(
                f"Không tải được {self.cfg.pipeline}. Kiểm tra HF token và đã chấp nhận "
                "điều khoản model trên huggingface.co chưa."
            )
        self.pipeline.to(torch.device(self.cfg.device))
        self._torch = torch

    def diarize(self, audio: np.ndarray) -> list[Turn]:
        waveform = self._torch.from_numpy(audio).unsqueeze(0)
        out = self.pipeline(
            {"waveform": waveform, "sample_rate": SAMPLE_RATE},
            num_speakers=self.cfg.num_speakers,
            min_speakers=self.cfg.min_speakers,
            max_speakers=self.cfg.max_speakers,
        )
        annotation = getattr(out, "speaker_diarization", out)  # pyannote 4 trả về object bọc
        return [
            Turn(round(seg.start, 3), round(seg.end, 3), spk)
            for seg, _, spk in annotation.itertracks(yield_label=True)
        ]


def assign_speakers(transcript: dict, turns: list[Turn]) -> dict:
    """Gán nhãn người nói cho từng segment/từ của WhisperX dựa trên độ chồng lấn thời gian."""
    import pandas as pd
    import whisperx

    df = pd.DataFrame([t.__dict__ for t in turns], columns=["start", "end", "speaker"])
    if df.empty:
        return transcript
    return whisperx.assign_word_speakers(df, transcript)
