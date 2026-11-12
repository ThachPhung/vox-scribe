"""Danh bạ giọng trên SQLite (DB của core_app) + tự học vân tay giọng sau mỗi cuộc họp.

`SqliteVoiceBook`: cùng interface `VoiceBook` với `JsonVoiceBook`, đọc hồ sơ từ `voice_profiles`
-> tên so khớp ra luôn tồn tại trong bảng `speakers`, core_app gán được ngay.

`VoiceLearner.learn()`: ghi thẳng sample 'auto' vào `voice_samples` theo luật đã chốt với TV3:
  1. Ngưỡng sàn: người đó phải nói >= `min_speech_sec` trong cuộc họp.
  2. Giới hạn: mỗi cuộc họp ghi tối đa `max_samples_per_meeting` sample/người,
     mỗi sample dựng từ >= `sample_sec` giây.
  3. Chỉ ghi khi khớp chắc: cosine >= `auto_threshold` (người mới, ít sample:
     `new_speaker_threshold`, cao hơn) và hơn người giống thứ 2 ít nhất `min_margin`.
  4. Kiểm tra lệch sau mỗi `check_every` cuộc họp có tự học: nếu sample gần đây xa
     "mỏ neo" (sample xác nhận tay / sample cũ) hoặc độ phân tán quá lớn -> đánh dấu
     sample gần đây 'suspect', TẠM DỪNG tự học, chờ người dùng xác nhận qua /speakers/confirm
     (confirm sẽ bật lại tự học).
  Người chưa có trong danh bạ: không tự tạo (không biết tên) -> cần /speakers/confirm.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core_app.database import voice_profiles as vp
from core_app.database.connection import initialize_database, open_connection, write_transaction

from .embedder import DEFAULT_MODEL, l2_normalize
from .speaker_matcher import Voiceprint


# ------------------------------------------------------------------ danh bạ
class SqliteVoiceBook:
    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection

    @classmethod
    def open(cls, db_path: str | Path) -> "SqliteVoiceBook":
        initialize_database(Path(db_path))  # tạo / nâng cấp schema (v3) nếu cần
        return cls(open_connection(Path(db_path)))

    def list(self, model: str | None = None) -> list[Voiceprint]:
        return [
            Voiceprint(str(p.speaker_id), p.name, l2_normalize(p.embedding), p.model_version, p.total_sec)
            for p in vp.list_profiles(self.conn, model or DEFAULT_MODEL)
        ]

    def get(self, speaker_id: str) -> Voiceprint | None:
        return next((v for v in self.list() if v.speaker_id == str(speaker_id)), None)

    def find_by_name(self, name: str, model: str | None = None) -> Voiceprint | None:
        key = name.strip().casefold()
        return next((v for v in self.list(model) if v.name.strip().casefold() == key), None)

    def upsert(self, v: Voiceprint) -> None:
        """Enroll tay (CLI): thêm sample 'manual' cho người tên `v.name`."""
        with write_transaction(self.conn):
            self.conn.execute("INSERT INTO speakers (name) VALUES (?) ON CONFLICT (name) DO NOTHING", (v.name,))
            sid = self.conn.execute("SELECT id FROM speakers WHERE name = ?", (v.name,)).fetchone()[0]
            vp.add_sample(self.conn, sid, v.model, v.embedding, source="manual", duration_sec=v.total_sec)
            vp.recompute_profile(self.conn, sid, v.model)
            vp.set_auto_learn(self.conn, sid, v.model, enabled=True)

    def delete(self, speaker_id: str) -> bool:
        with write_transaction(self.conn):
            return self.conn.execute("DELETE FROM speakers WHERE id = ?", (int(speaker_id),)).rowcount > 0

    def close(self) -> None:
        self.conn.close()


# ------------------------------------------------------------------ tự học
@dataclass
class LearningPolicy:
    min_speech_sec: float = 30.0
    sample_sec: float = 30.0
    max_samples_per_meeting: int = 2
    auto_threshold: float = 0.70
    new_speaker_threshold: float = 0.78
    new_speaker_max_samples: int = 5  # < số sample này coi là "người mới"
    min_margin: float = 0.10
    check_every: int = 5
    drift_min_sim: float = 0.65  # sample gần đây phải giống mỏ neo ít nhất chừng này
    drift_max_spread: float = 0.10  # độ lệch chuẩn cosine (sample -> tâm) tối đa


@dataclass
class Candidate:
    """1 người nói trong cuộc họp, do pipeline chuẩn bị."""

    label: str
    embedding: np.ndarray | None  # vector cả cụm (đã chuẩn hoá)
    speech_sec: float
    samples: list[tuple[np.ndarray, float]] = field(default_factory=list)  # (vector, số giây), mỗi cái >= sample_sec
    speaker_id: str | None = None  # do matcher gán (1-1)
    name_hint: str | None = None  # vd --mic-name cho SPEAKER_00


@dataclass
class LearnEvent:
    label: str
    name: str | None
    action: str  # learned | skipped | paused | checked
    detail: str


class VoiceLearner:
    def __init__(self, book: SqliteVoiceBook, model: str = DEFAULT_MODEL, policy: LearningPolicy | None = None):
        self.book = book
        self.conn = book.conn
        self.model = model
        self.p = policy or LearningPolicy()

    def learn(self, meeting_id: str, candidates: list[Candidate]) -> list[LearnEvent]:
        events: list[LearnEvent] = []
        for c in candidates:
            with write_transaction(self.conn):
                events += self._learn_one(meeting_id, c)
        return events

    def _learn_one(self, meeting_id: str, c: Candidate) -> list[LearnEvent]:
        skip = lambda name, why: [LearnEvent(c.label, name, "skipped", why)]
        profiles = vp.list_profiles(self.conn, self.model)
        prof = None
        if c.speaker_id is not None:
            prof = next((p for p in profiles if str(p.speaker_id) == str(c.speaker_id)), None)
        elif c.name_hint:
            key = c.name_hint.strip().casefold()
            prof = next((p for p in profiles if p.name.strip().casefold() == key), None)
        if prof is None:
            return skip(c.name_hint, "chưa có trong danh bạ / không khớp ai -> cần /speakers/confirm")
        if prof.auto_learn != "on":
            return skip(prof.name, f"tự học đang tạm dừng ({prof.paused_reason}) -> cần /speakers/confirm")
        if c.speech_sec < self.p.min_speech_sec:
            return skip(prof.name, f"mới nói {c.speech_sec:.0f}s < ngưỡng sàn {self.p.min_speech_sec:.0f}s")
        if c.embedding is None or not c.samples:
            return skip(prof.name, "không đủ âm thanh sạch để tạo sample")

        sims = {p.speaker_id: float(l2_normalize(p.embedding) @ c.embedding) for p in profiles}
        score = sims[prof.speaker_id]
        second = max((s for sid, s in sims.items() if sid != prof.speaker_id), default=-1.0)
        is_new = prof.sample_count < self.p.new_speaker_max_samples
        need = self.p.new_speaker_threshold if is_new else self.p.auto_threshold
        if score < need:
            kind = "người mới" if is_new else "ngưỡng tự học"
            return skip(prof.name, f"điểm {score:.3f} < {kind} {need:.2f}")
        if score - second < self.p.min_margin:
            return skip(prof.name, f"phân vân: hơn người thứ 2 chỉ {score - second:.3f} < {self.p.min_margin}")

        quota = self.p.max_samples_per_meeting - vp.count_auto_samples(self.conn, prof.speaker_id, self.model, meeting_id)
        if quota <= 0:
            return skip(prof.name, f"cuộc họp này đã ghi đủ {self.p.max_samples_per_meeting} sample")

        centroid = l2_normalize(prof.embedding)
        written = 0
        for emb, sec in sorted(c.samples, key=lambda x: -x[1]):
            if written >= quota:
                break
            s = float(centroid @ l2_normalize(emb))
            if s < need:  # từng sample cũng phải đạt ngưỡng
                continue
            vp.add_sample(
                self.conn, prof.speaker_id, self.model, emb, source="auto", duration_sec=sec,
                meeting_id=meeting_id, speaker_label=c.label, match_score=round(s, 4),
            )
            written += 1
        if not written:
            return skip(prof.name, "không sample nào đạt ngưỡng")
        vp.recompute_profile(self.conn, prof.speaker_id, self.model)
        events = [LearnEvent(c.label, prof.name, "learned", f"ghi {written} sample, điểm cụm {score:.3f}")]
        if vp.bump_auto_meeting(self.conn, prof.speaker_id, self.model) >= self.p.check_every:
            events.append(self.check_drift(prof.speaker_id, prof.name, c.label))
        return events

    def check_drift(self, speaker_id: int, name: str, label: str = "") -> LearnEvent:
        """So các sample tự học gần đây với mỏ neo; lệch nhiều -> tạm dừng tự học."""
        samples = vp.list_samples(self.conn, speaker_id, self.model)
        autos = [s for s in samples if s.source == "auto"]
        recent_meetings = list(dict.fromkeys(s.meeting_id for s in reversed(autos)))[: self.p.check_every]
        recent = [s for s in autos if s.meeting_id in recent_meetings]
        older = [s for s in samples if s not in recent]
        manual = [s for s in older if s.source == "manual"]
        anchor = vp.weighted_centroid(manual or older)
        centroid = vp.weighted_centroid(samples)
        if anchor is None or not recent or centroid is None:
            vp.reset_check_counter(self.conn, speaker_id, self.model)
            return LearnEvent(label, name, "checked", "chưa đủ dữ liệu mỏ neo, bỏ qua lần kiểm tra")

        recent_sim = float(np.mean([anchor @ l2_normalize(s.embedding) for s in recent]))
        spread = float(np.std([centroid @ l2_normalize(s.embedding) for s in samples]))
        if recent_sim < self.p.drift_min_sim or spread > self.p.drift_max_spread:
            # Cách ly: sample tự học gần đây + mọi sample tự học cũ hơn đã xa mỏ neo
            bad = {s.id for s in recent} | {
                s.id for s in autos if float(anchor @ l2_normalize(s.embedding)) < self.p.drift_min_sim
            }
            vp.mark_suspect(self.conn, sorted(bad))
            vp.recompute_profile(self.conn, speaker_id, self.model)
            reason = f"lệch: giống mỏ neo {recent_sim:.3f}, phân tán {spread:.3f}"
            vp.set_auto_learn(self.conn, speaker_id, self.model, enabled=False, reason=reason)
            return LearnEvent(label, name, "paused", f"{reason}; {len(bad)} sample tự học -> suspect")
        vp.reset_check_counter(self.conn, speaker_id, self.model)
        return LearnEvent(label, name, "checked", f"ổn: giống mỏ neo {recent_sim:.3f}, phân tán {spread:.3f}")


def make_samples(embedder, audio: np.ndarray, spans: list[tuple[float, float]], sample_sec: float) -> list[tuple[np.ndarray, float]]:
    """Gom các lượt nói liên tiếp thành từng nhóm >= sample_sec giây, mỗi nhóm -> 1 vector."""
    groups, cur, cur_sec = [], [], 0.0
    for s, e in spans:
        cur.append((s, e))
        cur_sec += e - s
        if cur_sec >= sample_sec:
            groups.append(cur)
            cur, cur_sec = [], 0.0
    out = []
    for g in groups:
        emb, sec = embedder.embed_segments(audio, g)
        if emb is not None:
            out.append((emb, sec))
    return out
