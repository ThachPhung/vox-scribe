"""So khớp Cosine Similarity để gán tên thật từ danh bạ giọng nói (Voice Book).

- `VoiceBook`: interface lưu trữ danh bạ. Hiện có `JsonVoiceBook` (file JSON, dùng tạm);
  core_app sẽ cài bản sqlite-vec theo cùng interface (list / get / upsert / delete).
- `SpeakerMatcher.match_clusters`: gán tên cho các cụm SPEAKER_xx theo kiểu 1-1
  (mỗi người trong danh bạ chỉ gán cho tối đa 1 cụm), chọn cặp có điểm cao nhất trước.
- CLI enroll / list / remove / identify để test nhanh:

    python -m speech_ai.speaker_matcher enroll "Thạch" samples/thach_*.wav
    python -m speech_ai.speaker_matcher list
    python -m speech_ai.speaker_matcher identify samples/unknown.wav
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from .embedder import DEFAULT_MODEL, Embedder, l2_normalize

DEFAULT_BOOK = Path(__file__).resolve().parents[1] / "data" / "voicebook.json"
DEFAULT_THRESHOLD = 0.55  # CAM++: cùng người ~0.75-0.85, khác người ~0.2-0.45


@dataclass
class Voiceprint:
    speaker_id: str
    name: str
    embedding: np.ndarray  # đã chuẩn hoá L2
    model: str  # tên model embedding (vector khác model không so được)
    total_sec: float = 0.0  # tổng số giây âm thanh đã dùng để enroll (làm trọng số khi cập nhật)
    updated_at: float = 0.0


class VoiceBook(Protocol):
    def list(self, model: str | None = None) -> list[Voiceprint]: ...
    def get(self, speaker_id: str) -> Voiceprint | None: ...
    def upsert(self, vp: Voiceprint) -> None: ...
    def delete(self, speaker_id: str) -> bool: ...


class JsonVoiceBook:
    """Danh bạ lưu file JSON. Đủ dùng cho PoC / vài trăm người."""

    def __init__(self, path: str | Path = DEFAULT_BOOK):
        self.path = Path(path)
        self._items: dict[str, Voiceprint] = {}
        if self.path.exists():
            for d in json.loads(self.path.read_text(encoding="utf-8")):
                d["embedding"] = np.asarray(d["embedding"], np.float32)
                self._items[d["speaker_id"]] = Voiceprint(**d)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {**vp.__dict__, "embedding": [round(float(x), 6) for x in vp.embedding]} for vp in self._items.values()
        ]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def list(self, model: str | None = None) -> list[Voiceprint]:
        return [v for v in self._items.values() if model is None or v.model == model]

    def get(self, speaker_id: str) -> Voiceprint | None:
        return self._items.get(speaker_id)

    def find_by_name(self, name: str, model: str | None = None) -> Voiceprint | None:
        key = name.strip().casefold()
        return next((v for v in self.list(model) if v.name.strip().casefold() == key), None)

    def upsert(self, vp: Voiceprint) -> None:
        self._items[vp.speaker_id] = vp
        self._save()

    def delete(self, speaker_id: str) -> bool:
        ok = self._items.pop(speaker_id, None) is not None
        if ok:
            self._save()
        return ok


@dataclass
class Match:
    label: str  # SPEAKER_xx
    speaker_id: str | None
    name: str | None
    score: float  # cosine với người khớp nhất (kể cả khi dưới ngưỡng)


class SpeakerMatcher:
    def __init__(self, book: VoiceBook, model: str = DEFAULT_MODEL, threshold: float = DEFAULT_THRESHOLD):
        self.book = book
        self.model = model
        self.threshold = threshold

    def scores(self, embedding: np.ndarray) -> list[tuple[Voiceprint, float]]:
        """Điểm cosine với mọi người trong danh bạ, giảm dần."""
        entries = self.book.list(self.model)
        if not entries:
            return []
        mat = np.stack([e.embedding for e in entries])
        sims = mat @ l2_normalize(embedding)
        return sorted(zip(entries, map(float, sims)), key=lambda x: -x[1])

    def match(self, embedding: np.ndarray, label: str = "") -> Match:
        top = self.scores(embedding)
        if top and top[0][1] >= self.threshold:
            vp, s = top[0]
            return Match(label, vp.speaker_id, vp.name, round(s, 4))
        return Match(label, None, None, round(top[0][1], 4) if top else 0.0)

    def match_clusters(self, centroids: dict[str, np.ndarray]) -> dict[str, Match]:
        """Gán 1-1: cặp (cụm, người) điểm cao nhất được chọn trước, mỗi bên dùng 1 lần."""
        entries = self.book.list(self.model)
        result = {lab: Match(lab, None, None, 0.0) for lab in centroids}
        if not entries or not centroids:
            return result
        labels = list(centroids)
        sims = np.stack([l2_normalize(centroids[l]) for l in labels]) @ np.stack([e.embedding for e in entries]).T
        for i, lab in enumerate(labels):
            result[lab].score = round(float(sims[i].max()), 4)
        used_l, used_e = set(), set()
        for flat in np.argsort(-sims, axis=None):
            i, j = divmod(int(flat), sims.shape[1])
            if sims[i, j] < self.threshold:
                break
            if i in used_l or j in used_e:
                continue
            used_l.add(i)
            used_e.add(j)
            result[labels[i]] = Match(labels[i], entries[j].speaker_id, entries[j].name, round(float(sims[i, j]), 4))
        return result

    def enroll(self, name: str, embedding: np.ndarray, seconds: float, speaker_id: str | None = None) -> Voiceprint:
        """Thêm người mới, hoặc cập nhật vân tay (trung bình có trọng số theo số giây) nếu đã có."""
        existing = self.book.get(speaker_id) if speaker_id else None
        if existing is None and hasattr(self.book, "find_by_name"):
            existing = self.book.find_by_name(name, self.model)
        emb = l2_normalize(embedding)
        if existing is not None and existing.model == self.model:
            total = existing.total_sec + seconds
            emb = l2_normalize(existing.embedding * existing.total_sec + emb * seconds)
            vp = Voiceprint(existing.speaker_id, name, emb, self.model, round(total, 2), time.time())
        else:
            vp = Voiceprint(speaker_id or uuid.uuid4().hex[:12], name, emb, self.model, round(seconds, 2), time.time())
        self.book.upsert(vp)
        return vp


# ------------------------------------------------------------------ CLI
def _embed_files(embedder: Embedder, files: list[str]) -> tuple[np.ndarray, float]:
    from .audio_chunker import SAMPLE_RATE, load_audio

    vecs, secs = [], []
    for f in files:
        a = load_audio(f)
        v = embedder.embed(a)
        if v is None:
            print(f"  bỏ qua {f}: quá ngắn")
            continue
        vecs.append(v)
        secs.append(len(a) / SAMPLE_RATE)
    if not vecs:
        raise SystemExit("Không có file nào dùng được")
    w = np.array(secs, np.float32)
    return l2_normalize((np.stack(vecs) * w[:, None]).sum(0)), float(w.sum())


def main() -> None:
    p = argparse.ArgumentParser(description="Danh bạ giọng nói VoxScribe")
    p.add_argument("--book", default=str(DEFAULT_BOOK))
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enroll", help="Thêm / cập nhật giọng một người từ các file âm thanh")
    e.add_argument("name")
    e.add_argument("files", nargs="+")
    sub.add_parser("list")
    r = sub.add_parser("remove")
    r.add_argument("speaker_id")
    i = sub.add_parser("identify", help="Đoán file âm thanh là giọng của ai")
    i.add_argument("files", nargs="+")
    a = p.parse_args()

    book = JsonVoiceBook(a.book)
    matcher = SpeakerMatcher(book, a.model, a.threshold)
    if a.cmd == "list":
        for vp in book.list():
            print(f"{vp.speaker_id}  {vp.name:20s} {vp.model} dim={len(vp.embedding)} {vp.total_sec:.1f}s")
        return
    if a.cmd == "remove":
        print("Đã xoá" if book.delete(a.speaker_id) else "Không tìm thấy")
        return
    embedder = Embedder(a.model)
    if a.cmd == "enroll":
        emb, secs = _embed_files(embedder, a.files)
        vp = matcher.enroll(a.name, emb, secs)
        print(f"Đã lưu {vp.name} ({vp.speaker_id}), tổng {vp.total_sec:.1f}s âm thanh")
    elif a.cmd == "identify":
        from .audio_chunker import load_audio

        for f in a.files:
            v = embedder.embed(load_audio(f))
            if v is None:
                print(f"{f}: quá ngắn")
                continue
            m = matcher.match(v)
            top = ", ".join(f"{vp.name}={s:.3f}" for vp, s in matcher.scores(v)[:3])
            print(f"{f}: {m.name or 'KHÔNG RÕ'}  [{top}]")


if __name__ == "__main__":
    main()
