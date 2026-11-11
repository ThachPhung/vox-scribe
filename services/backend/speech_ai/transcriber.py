"""Chạy WhisperX chuyển âm thanh thành chữ + timestamp.

Hai bước:
1. faster-whisper (qua WhisperX) phiên âm theo câu, có VAD + batching.
2. wav2vec2 alignment để có timestamp chính xác đến từng từ
   (cần cho bước gán người nói theo từ).
"""
from __future__ import annotations

import gc
from dataclasses import dataclass

import numpy as np

from .audio_chunker import SAMPLE_RATE

# Model align mặc định của WhisperX cho "vi" (wav2vec2-base-vi-vlsp2020) có kiến trúc riêng,
# nạp vào Wav2Vec2ForCTC bị mất weight -> timestamp bị nén ~4 lần. Dùng model chuẩn thay thế.
ALIGN_MODELS = {"vi": "nguyenvulebinh/wav2vec2-base-vietnamese-250h"}


@dataclass
class TranscriberConfig:
    model: str = "large-v3"  # tiny | base | small | medium | large-v3 | large-v3-turbo
    language: str | None = "vi"  # None = tự nhận diện
    device: str = "cpu"  # faster-whisper chỉ hỗ trợ cpu / cuda (không có mps)
    compute_type: str = "int8"  # cuda: float16 ; cpu: int8
    batch_size: int = 8
    align_model: str | None = None  # None = ALIGN_MODELS[lang] hoặc mặc định của WhisperX


class Transcriber:
    def __init__(self, cfg: TranscriberConfig | None = None):
        import whisperx

        self.cfg = cfg or TranscriberConfig()
        self._wx = whisperx
        self.model = whisperx.load_model(
            self.cfg.model,
            self.cfg.device,
            compute_type=self.cfg.compute_type,
            language=self.cfg.language,
        )
        self._align_model = None
        self._align_meta = None
        self._align_lang = None

    def transcribe(self, audio: np.ndarray, align: bool = True) -> dict:
        """Trả về dict WhisperX: {"language", "segments": [{start, end, text, words?}]}."""
        result = self.model.transcribe(
            audio, batch_size=self.cfg.batch_size, language=self.cfg.language
        )
        language = result.get("language") or self.cfg.language
        if align and result["segments"]:
            result = self._align(result["segments"], audio, language)
        result["language"] = language
        return result

    def _align(self, segments: list[dict], audio: np.ndarray, language: str) -> dict:
        if self._align_lang != language:
            self._align_model, self._align_meta = self._wx.load_align_model(
                language_code=language,
                device=self.cfg.device,
                model_name=self.cfg.align_model or ALIGN_MODELS.get(language),
            )
            self._align_lang = language
        return self._wx.align(
            segments,
            self._align_model,
            self._align_meta,
            audio,
            self.cfg.device,
            return_char_alignments=False,
        )

    def close(self) -> None:
        del self.model, self._align_model
        gc.collect()


def duration_sec(audio: np.ndarray) -> float:
    return len(audio) / SAMPLE_RATE
