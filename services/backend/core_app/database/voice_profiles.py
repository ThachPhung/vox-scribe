"""Truy vấn sample / hồ sơ vân tay giọng (schema v3).

Dùng chung cho:
- core_app: `/speakers/confirm` thêm sample 'manual' rồi tính lại hồ sơ.
- speech_ai.voice_learning: tự học (ghi thẳng) sample 'auto' sau mỗi cuộc họp.

Các hàm ở đây KHÔNG tự mở transaction; người gọi bọc trong `write_transaction`.
"""
import sqlite3
from dataclasses import dataclass

import numpy as np
import sqlite_vec

from core_app.database.models import EMBEDDING_DIM, SQL_NOW

MANUAL_WEIGHT = 2.0  # sample người dùng xác nhận đáng tin hơn sample tự học
MIN_WEIGHT_SEC = 10.0  # sample tự học tối thiểu tính 10s
MANUAL_MIN_SEC = 30.0  # sample xác nhận tay (API không gửi số giây) tối thiểu tính 30s


@dataclass
class VoiceProfile:
    speaker_id: int
    name: str
    model_version: str
    embedding: np.ndarray
    sample_count: int
    total_sec: float
    auto_learn: str  # 'on' | 'paused'
    paused_reason: str | None
    auto_meetings_since_check: int


@dataclass
class VoiceSample:
    id: int
    embedding: np.ndarray
    duration_sec: float
    source: str
    status: str
    meeting_id: str | None
    match_score: float | None


def _to_blob(values) -> bytes:
    arr = np.asarray(values, np.float32).reshape(-1)
    if arr.shape[0] != EMBEDDING_DIM:
        raise ValueError(f"Vector giọng phải có {EMBEDDING_DIM} chiều, nhận {arr.shape[0]}")
    return sqlite_vec.serialize_float32(arr.tolist())


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, np.float32).copy()


def _normalize(v: np.ndarray) -> np.ndarray:
    return v / max(float(np.linalg.norm(v)), 1e-12)


def add_sample(
    connection: sqlite3.Connection,
    speaker_id: int,
    model_version: str,
    embedding,
    *,
    source: str,
    duration_sec: float = 0.0,
    meeting_id: str | None = None,
    speaker_label: str | None = None,
    match_score: float | None = None,
) -> int:
    cur = connection.execute(
        "INSERT INTO voice_samples (speaker_id, model_version, embedding, duration_sec, source,"
        " meeting_id, speaker_label, match_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (speaker_id, model_version, _to_blob(embedding), float(duration_sec), source, meeting_id, speaker_label, match_score),
    )
    return int(cur.lastrowid)


def list_samples(
    connection: sqlite3.Connection, speaker_id: int, model_version: str, statuses: tuple[str, ...] = ("active",)
) -> list[VoiceSample]:
    marks = ",".join("?" * len(statuses))
    rows = connection.execute(
        f"SELECT id, embedding, duration_sec, source, status, meeting_id, match_score FROM voice_samples"
        f" WHERE speaker_id = ? AND model_version = ? AND status IN ({marks}) ORDER BY id",
        (speaker_id, model_version, *statuses),
    ).fetchall()
    return [
        VoiceSample(r["id"], _from_blob(r["embedding"]), r["duration_sec"], r["source"], r["status"], r["meeting_id"], r["match_score"])
        for r in rows
    ]


def weighted_centroid(samples: list[VoiceSample]) -> np.ndarray | None:
    if not samples:
        return None
    w = np.array(
        [
            max(s.duration_sec, MANUAL_MIN_SEC) * MANUAL_WEIGHT if s.source == "manual" else max(s.duration_sec, MIN_WEIGHT_SEC)
            for s in samples
        ],
        np.float32,
    )
    vecs = np.stack([_normalize(s.embedding) for s in samples])
    return _normalize((vecs * w[:, None]).sum(0))


def recompute_profile(connection: sqlite3.Connection, speaker_id: int, model_version: str) -> np.ndarray | None:
    """Tính lại vector hồ sơ từ các sample 'active'. Không còn sample nào thì xoá hồ sơ."""
    samples = list_samples(connection, speaker_id, model_version)
    centroid = weighted_centroid(samples)
    if centroid is None:
        connection.execute(
            "DELETE FROM voice_profiles WHERE speaker_id = ? AND model_version = ?", (speaker_id, model_version)
        )
        return None
    connection.execute(
        f"""
        INSERT INTO voice_profiles (speaker_id, model_version, embedding, sample_count, total_sec)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (speaker_id, model_version) DO UPDATE SET
            embedding = excluded.embedding,
            sample_count = excluded.sample_count,
            total_sec = excluded.total_sec,
            updated_at = {SQL_NOW}
        """,
        (speaker_id, model_version, _to_blob(centroid), len(samples), float(sum(s.duration_sec for s in samples))),
    )
    return centroid


def list_profiles(connection: sqlite3.Connection, model_version: str) -> list[VoiceProfile]:
    rows = connection.execute(
        """
        SELECT v.speaker_id, s.name, v.model_version, v.embedding, v.sample_count, v.total_sec,
               v.auto_learn, v.paused_reason, v.auto_meetings_since_check
        FROM voice_profiles v JOIN speakers s ON s.id = v.speaker_id
        WHERE v.model_version = ?
        ORDER BY s.name
        """,
        (model_version,),
    ).fetchall()
    return [
        VoiceProfile(
            r["speaker_id"], r["name"], r["model_version"], _from_blob(r["embedding"]), r["sample_count"],
            r["total_sec"], r["auto_learn"], r["paused_reason"], r["auto_meetings_since_check"],
        )
        for r in rows
    ]


def get_profile(connection: sqlite3.Connection, speaker_id: int, model_version: str) -> VoiceProfile | None:
    return next((p for p in list_profiles(connection, model_version) if p.speaker_id == speaker_id), None)


def set_auto_learn(
    connection: sqlite3.Connection, speaker_id: int, model_version: str, enabled: bool, reason: str | None = None
) -> None:
    connection.execute(
        f"UPDATE voice_profiles SET auto_learn = ?, paused_reason = ?, auto_meetings_since_check = 0,"
        f" updated_at = {SQL_NOW} WHERE speaker_id = ? AND model_version = ?",
        ("on" if enabled else "paused", None if enabled else reason, speaker_id, model_version),
    )


def bump_auto_meeting(connection: sqlite3.Connection, speaker_id: int, model_version: str) -> int:
    connection.execute(
        "UPDATE voice_profiles SET auto_meetings_since_check = auto_meetings_since_check + 1"
        " WHERE speaker_id = ? AND model_version = ?",
        (speaker_id, model_version),
    )
    row = connection.execute(
        "SELECT auto_meetings_since_check FROM voice_profiles WHERE speaker_id = ? AND model_version = ?",
        (speaker_id, model_version),
    ).fetchone()
    return int(row[0]) if row else 0


def reset_check_counter(connection: sqlite3.Connection, speaker_id: int, model_version: str) -> None:
    connection.execute(
        "UPDATE voice_profiles SET auto_meetings_since_check = 0 WHERE speaker_id = ? AND model_version = ?",
        (speaker_id, model_version),
    )


def count_auto_samples(connection: sqlite3.Connection, speaker_id: int, model_version: str, meeting_id: str) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM voice_samples WHERE speaker_id = ? AND model_version = ?"
            " AND meeting_id = ? AND source = 'auto'",
            (speaker_id, model_version, meeting_id),
        ).fetchone()[0]
    )


def mark_suspect(connection: sqlite3.Connection, sample_ids: list[int]) -> None:
    connection.executemany("UPDATE voice_samples SET status = 'suspect' WHERE id = ?", [(i,) for i in sample_ids])
