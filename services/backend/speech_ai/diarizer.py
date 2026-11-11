"""Tách các giọng nói (SPEAKER_00, 01...) bằng sherpa-onnx (C++/ONNX Runtime).

Luồng bên trong sherpa-onnx (tương đương pyannote 3.1 nhưng không cần PyTorch / HF token):
    pyannote/segmentation-3.0 (ONNX) -> embedding giọng (WeSpeaker ResNet34 ONNX)
    -> gom cụm (FastClustering) -> danh sách lượt nói [start, end, speaker]
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .audio_chunker import SAMPLE_RATE

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
DEFAULT_SEGMENTATION = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
DEFAULT_EMBEDDING = MODELS_DIR / "wespeaker_en_voxceleb_resnet34_LM.onnx"


@dataclass
class DiarizerConfig:
    segmentation_model: str | Path = DEFAULT_SEGMENTATION
    embedding_model: str | Path = DEFAULT_EMBEDDING
    num_speakers: int | None = None  # biết trước số người -> chính xác hơn
    threshold: float = 0.5  # khi không biết số người: nhỏ hơn -> nhiều người hơn
    min_duration_on: float = 0.3
    min_duration_off: float = 0.5
    num_threads: int | None = None


@dataclass
class Turn:
    start: float
    end: float
    speaker: str


class Diarizer:
    def __init__(self, cfg: DiarizerConfig | None = None):
        import sherpa_onnx as so

        self.cfg = c = cfg or DiarizerConfig()
        for p in (c.segmentation_model, c.embedding_model):
            if not Path(p).exists():
                raise FileNotFoundError(f"Thiếu model {p}. Chạy scripts/download_models.py")
        threads = c.num_threads or max(1, (os.cpu_count() or 2) // 2)
        config = so.OfflineSpeakerDiarizationConfig(
            segmentation=so.OfflineSpeakerSegmentationModelConfig(
                pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(c.segmentation_model)),
                num_threads=threads,
            ),
            embedding=so.SpeakerEmbeddingExtractorConfig(model=str(c.embedding_model), num_threads=threads),
            clustering=so.FastClusteringConfig(
                num_clusters=c.num_speakers or -1, threshold=c.threshold
            ),
            min_duration_on=c.min_duration_on,
            min_duration_off=c.min_duration_off,
        )
        if not config.validate():
            raise RuntimeError("Cấu hình diarization không hợp lệ, kiểm tra đường dẫn model")
        self.sd = so.OfflineSpeakerDiarization(config)
        assert self.sd.sample_rate == SAMPLE_RATE

    def diarize(self, audio: np.ndarray) -> list[Turn]:
        result = self.sd.process(audio).sort_by_start_time()
        return [Turn(round(r.start, 3), round(r.end, 3), f"SPEAKER_{r.speaker:02d}") for r in result]


def merge_turns(turns: list[Turn], max_gap: float = 0.5) -> list[Turn]:
    """Gộp các lượt liền kề cùng người nói (cách nhau <= max_gap giây)."""
    merged: list[Turn] = []
    for t in turns:
        if merged and merged[-1].speaker == t.speaker and t.start - merged[-1].end <= max_gap:
            merged[-1].end = max(merged[-1].end, t.end)
        else:
            merged.append(Turn(t.start, t.end, t.speaker))
    return merged
