"""Tách các giọng nói (SPEAKER_01, SPEAKER_02...) bằng sherpa-onnx (C++/ONNX Runtime).

Hai tầng:
1. sherpa-onnx: pyannote/segmentation-3.0 (ONNX) -> embedding CAM++ từng đoạn ngắn
   -> FastClustering. Tầng này hay tách thừa 1 người thành 2-3 cụm.
2. `refine_clusters` (của mình): tính lại vector đại diện cho CẢ cụm (ổn định hơn nhiều so với
   đoạn ngắn), rồi gộp dần các cặp cụm giống nhau nhất (agglomerative, cosine) cho tới khi
   độ giống < `merge_threshold` hoặc đủ `num_speakers`. Cụm quá ngắn được gán vào cụm gần nhất.
   Cuối cùng đánh lại nhãn theo thứ tự xuất hiện, bắt đầu từ `label_offset`
   (Kênh Phải dùng offset 1 -> SPEAKER_01, 02...; SPEAKER_00 dành cho Mic).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio_chunker import SAMPLE_RATE
from .embedder import MODELS, Embedder, l2_normalize

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
DEFAULT_SEGMENTATION = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
DEFAULT_EMBEDDING = MODELS_DIR / MODELS["campplus"]


@dataclass
class DiarizerConfig:
    segmentation_model: str | Path = DEFAULT_SEGMENTATION
    embedding_model: str | Path = DEFAULT_EMBEDDING
    num_speakers: int | None = None  # biết trước số người -> gộp tới đúng số này
    threshold: float = 0.5  # ngưỡng FastClustering của sherpa (tầng 1, cố ý để tách hơi thừa)
    merge_threshold: float = 0.65  # cosine giữa 2 tâm cụm >= ngưỡng này -> cùng 1 người
    min_cluster_sec: float = 1.0  # cụm tổng < ngưỡng này bị gán vào cụm gần nhất
    min_duration_on: float = 0.3
    min_duration_off: float = 0.5
    label_offset: int = 1
    refine: bool = True
    num_threads: int | None = None


@dataclass
class Turn:
    start: float
    end: float
    speaker: str


@dataclass
class DiarizationResult:
    turns: list[Turn]
    centroids: dict[str, np.ndarray] = field(default_factory=dict)  # nhãn -> vector đã chuẩn hoá
    durations: dict[str, float] = field(default_factory=dict)  # nhãn -> tổng giây nói


class Diarizer:
    def __init__(self, cfg: DiarizerConfig | None = None, embedder: Embedder | None = None):
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
            # Khi refine: luôn để sherpa tự đoán (tách hơi thừa), việc gộp về đúng N do refine làm.
            # Lý do: ép num_clusters ở tầng 1 có lúc dồn cả 2 người vào 1 cụm.
            clustering=so.FastClusteringConfig(
                num_clusters=-1 if c.refine else (c.num_speakers or -1), threshold=c.threshold
            ),
            min_duration_on=c.min_duration_on,
            min_duration_off=c.min_duration_off,
        )
        if not config.validate():
            raise RuntimeError("Cấu hình diarization không hợp lệ, kiểm tra đường dẫn model")
        self.sd = so.OfflineSpeakerDiarization(config)
        assert self.sd.sample_rate == SAMPLE_RATE
        self.embedder = embedder or (Embedder(str(c.embedding_model)) if c.refine else None)

    def diarize(self, audio: np.ndarray) -> DiarizationResult:
        raw = self.sd.process(audio).sort_by_start_time()
        turns = [Turn(round(r.start, 3), round(r.end, 3), f"RAW_{r.speaker}") for r in raw]
        if not turns:
            return DiarizationResult([])
        if self.cfg.refine and self.embedder is not None:
            return refine_clusters(audio, turns, self.embedder, self.cfg)
        return _relabel(turns, {}, self.cfg.label_offset)


def refine_clusters(audio: np.ndarray, turns: list[Turn], embedder: Embedder, cfg: DiarizerConfig) -> DiarizationResult:
    labels = list(dict.fromkeys(t.speaker for t in turns))
    cent: dict[str, np.ndarray | None] = {}
    dur: dict[str, float] = {}
    for lab in labels:
        cent[lab], dur[lab] = embedder.embed_segments(audio, [(t.start, t.end) for t in turns if t.speaker == lab])
        if cent[lab] is None:  # cụm toàn đoạn quá ngắn
            dur[lab] = sum(t.end - t.start for t in turns if t.speaker == lab)
    mapping = {lab: lab for lab in labels}

    def root(x: str) -> str:
        while mapping[x] != x:
            x = mapping[x]
        return x

    def merge(dst: str, src: str) -> None:
        a, b = cent[dst], cent[src]
        if a is not None and b is not None:
            cent[dst] = l2_normalize(a * dur[dst] + b * dur[src])
        elif a is None:
            cent[dst] = b
        dur[dst] += dur[src]
        mapping[src] = dst
        active.remove(src)

    active = [l for l in labels]
    # 1) Gộp agglomerative theo cosine giữa các tâm cụm
    while len(active) > 1:
        best, pair = -2.0, None
        for i, x in enumerate(active):
            for y in active[i + 1 :]:
                if cent[x] is None or cent[y] is None:
                    continue
                s = float(cent[x] @ cent[y])
                if s > best:
                    best, pair = s, (x, y)
        if pair is None:
            break
        too_many = cfg.num_speakers is not None and len(active) > cfg.num_speakers
        if best >= cfg.merge_threshold or too_many:
            x, y = pair
            merge(x, y) if dur[x] >= dur[y] else merge(y, x)
        else:
            break
    # 2) Cụm quá ngắn / không có vector -> gán vào cụm lớn gần nhất
    for lab in sorted(active, key=lambda l: dur[l]):
        if len(active) <= 1 or (dur[lab] >= cfg.min_cluster_sec and cent[lab] is not None):
            continue
        others = [o for o in active if o != lab and cent[o] is not None]
        if not others:
            continue
        dst = max(others, key=lambda o: float(cent[o] @ cent[lab]) if cent[lab] is not None else dur[o])
        merge(dst, lab)

    merged = [Turn(t.start, t.end, root(t.speaker)) for t in turns]
    return _relabel(merged, {l: cent[l] for l in active if cent[l] is not None}, cfg.label_offset, dur)


def _relabel(
    turns: list[Turn], centroids: dict[str, np.ndarray], offset: int, durations: dict[str, float] | None = None
) -> DiarizationResult:
    order = list(dict.fromkeys(t.speaker for t in turns))
    names = {old: f"SPEAKER_{i + offset:02d}" for i, old in enumerate(order)}
    new_turns = merge_turns([Turn(t.start, t.end, names[t.speaker]) for t in turns])
    dur = {names[k]: 0.0 for k in order}
    for t in new_turns:
        dur[t.speaker] += t.end - t.start
    return DiarizationResult(
        new_turns,
        {names[k]: v for k, v in centroids.items() if k in names},
        {k: round(v, 2) for k, v in dur.items()},
    )


def merge_turns(turns: list[Turn], max_gap: float = 0.5) -> list[Turn]:
    """Gộp các lượt liền kề cùng người nói (cách nhau <= max_gap giây)."""
    merged: list[Turn] = []
    for t in sorted(turns, key=lambda x: x.start):
        if merged and merged[-1].speaker == t.speaker and t.start - merged[-1].end <= max_gap:
            merged[-1].end = max(merged[-1].end, t.end)
        else:
            merged.append(Turn(t.start, t.end, t.speaker))
    return merged
