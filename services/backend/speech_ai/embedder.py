"""Trích xuất vector vân tay giọng nói (Voiceprint) bằng ONNX qua sherpa-onnx.

Model mặc định: 3D-Speaker CAM++ (zh+en, 16kHz) -> vector **192 chiều**, ~28MB.
Có thể đổi sang WeSpeaker ResNet34-LM (256 chiều) bằng `model="wespeaker"`.

Quy ước (thống nhất với core_app / sqlite-vec):
- Vector float32, đã chuẩn hoá L2 (‖v‖ = 1) -> cosine similarity = tích vô hướng.
- Lưu kèm tên model (`Embedder.model_name`) vì vector của 2 model khác nhau không so được với nhau.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import numpy as np

from .audio_chunker import SAMPLE_RATE

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
MODELS = {
    "campplus": "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",  # 192 chiều
    "wespeaker": "wespeaker_en_voxceleb_resnet34_LM.onnx",  # 256 chiều, không tải mặc định
}
DEFAULT_MODEL = "campplus"


def l2_normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, np.float32)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-12)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(l2_normalize(a), l2_normalize(b)))


class Embedder:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        num_threads: int | None = None,
        min_sec: float = 0.5,
        max_window_sec: float = 10.0,
    ):
        import sherpa_onnx as so

        path = Path(model) if model.endswith(".onnx") else MODELS_DIR / MODELS[model]
        if not path.exists():
            raise FileNotFoundError(f"Thiếu model {path}. Chạy scripts/download_models.py")
        cfg = so.SpeakerEmbeddingExtractorConfig(
            model=str(path), num_threads=num_threads or max(1, (os.cpu_count() or 2) // 2)
        )
        if not cfg.validate():
            raise RuntimeError(f"Model embedding không hợp lệ: {path}")
        self.extractor = so.SpeakerEmbeddingExtractor(cfg)
        self.model_name = model if not model.endswith(".onnx") else path.stem
        self.dim: int = self.extractor.dim
        self.min_samples = int(min_sec * SAMPLE_RATE)
        self.window = int(max_window_sec * SAMPLE_RATE)

    def embed(self, audio: np.ndarray) -> np.ndarray | None:
        """Vector đã chuẩn hoá của 1 đoạn âm thanh. Đoạn quá ngắn (< min_sec) trả về None.

        Đoạn dài được chia cửa sổ `max_window_sec` rồi lấy trung bình (theo độ dài).
        """
        audio = np.asarray(audio, np.float32)
        if len(audio) < self.min_samples:
            return None
        parts = [audio[i : i + self.window] for i in range(0, len(audio), self.window)]
        parts = [p for p in parts if len(p) >= self.min_samples] or [audio]
        vecs = np.stack([self._embed_one(p) for p in parts])
        weights = np.array([len(p) for p in parts], np.float32)
        return l2_normalize((vecs * weights[:, None]).sum(0))

    def _embed_one(self, audio: np.ndarray) -> np.ndarray:
        s = self.extractor.create_stream()
        s.accept_waveform(SAMPLE_RATE, audio)
        s.input_finished()
        return l2_normalize(np.array(self.extractor.compute(s), np.float32))

    def embed_segments(
        self, audio: np.ndarray, spans: Iterable[tuple[float, float]]
    ) -> tuple[np.ndarray | None, float]:
        """Vector đại diện (centroid) cho 1 người từ nhiều đoạn [start, end] (giây) trong `audio`.

        Trả về (vector | None, tổng số giây đã dùng).
        """
        vecs, weights = [], []
        for start, end in spans:
            piece = audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
            v = self.embed(piece)
            if v is not None:
                vecs.append(v)
                weights.append(len(piece) / SAMPLE_RATE)
        if not vecs:
            return None, 0.0
        w = np.array(weights, np.float32)
        return l2_normalize((np.stack(vecs) * w[:, None]).sum(0)), float(w.sum())
