"""Các hàm truy vấn dữ liệu và tìm kiếm vector giọng."""
import json
import sqlite3
import uuid
from datetime import UTC, datetime

import sqlite_vec

from core_app.database import voice_profiles
from core_app.database.connection import write_transaction
from core_app.database.models import (
    SQL_NOW,
    CaptureMode,
    Meeting,
    MeetingSpeaker,
    MeetingStatus,
    Report,
    ReportDraft,
    Segment,
    Speaker,
    SpeakerConfirmation,
    SpeakerMatch,
    Transcript,
    TranscriptIn,
    TranscriptSegmentIn,
    VoiceEmbedding,
    normalize_person_name,
)

DEFAULT_MATCH_LIMIT = 3


class NotFoundError(LookupError):
    pass


class ConflictError(Exception):
    pass


def create_meeting(connection: sqlite3.Connection, title: str, capture_mode: CaptureMode) -> Meeting:
    meeting_id = uuid.uuid4().hex
    with write_transaction(connection):
        connection.execute(
            "INSERT INTO meetings (id, title, started_at, capture_mode, status) VALUES (?, ?, ?, ?, ?)",
            (meeting_id, title, datetime.now(UTC).isoformat(), capture_mode, MeetingStatus.RECORDING),
        )
    return get_meeting(connection, meeting_id)


def list_meetings(connection: sqlite3.Connection) -> list[Meeting]:
    rows = connection.execute("SELECT * FROM meetings ORDER BY started_at DESC").fetchall()
    return [Meeting.model_validate(dict(row)) for row in rows]


def get_meeting(connection: sqlite3.Connection, meeting_id: str) -> Meeting:
    row = connection.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Không tìm thấy cuộc họp {meeting_id}")
    return Meeting.model_validate(dict(row))


def delete_meeting(connection: sqlite3.Connection, meeting_id: str) -> None:
    with write_transaction(connection):
        deleted = connection.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,)).rowcount
        if deleted == 0:
            raise NotFoundError(f"Không tìm thấy cuộc họp {meeting_id}")


def finish_recording(connection: sqlite3.Connection, meeting_id: str) -> Meeting:
    """Chỉ một request kết thúc được cuộc họp; thời lượng tính từ started_at tới lúc kết thúc."""
    with write_transaction(connection):
        updated = connection.execute(
            """
            UPDATE meetings
            SET status = ?, duration_sec = MAX(0, (julianday('now') - julianday(started_at)) * 86400)
            WHERE id = ? AND status = ?
            """,
            (MeetingStatus.RECORDED, meeting_id, MeetingStatus.RECORDING),
        ).rowcount
    meeting = get_meeting(connection, meeting_id)
    if updated == 0:
        raise ConflictError(f"Cuộc họp {meeting_id} không ở trạng thái đang ghi")
    return meeting


def save_transcript(connection: sqlite3.Connection, transcript: TranscriptIn) -> Transcript:
    """Thay toàn bộ transcript và tăng số phiên bản; biên bản tạo từ phiên bản cũ trở thành stale.

    Tên do máy so khớp (speaker_name) chỉ ghi đè nhãn mà người dùng chưa xác nhận.
    """
    meeting_id = transcript.meeting_id
    names_by_label = _speaker_names_by_label(transcript.segments)
    with write_transaction(connection):
        bumped = connection.execute(
            "UPDATE meetings SET transcript_revision = transcript_revision + 1 WHERE id = ?", (meeting_id,)
        ).rowcount
        if bumped == 0:
            raise NotFoundError(f"Không tìm thấy cuộc họp {meeting_id}")
        connection.execute("DELETE FROM segments WHERE meeting_id = ?", (meeting_id,))
        _remove_stale_labels(connection, meeting_id, set(names_by_label))
        connection.executemany(
            """
            INSERT INTO meeting_speakers (meeting_id, speaker_label, speaker_id)
            VALUES (?, ?, (SELECT id FROM speakers WHERE name = ?))
            ON CONFLICT (meeting_id, speaker_label) DO UPDATE SET speaker_id = excluded.speaker_id
            WHERE meeting_speakers.confirmed_at IS NULL
            """,
            [(meeting_id, label, name) for label, name in names_by_label.items()],
        )
        connection.executemany(
            "INSERT INTO segments (meeting_id, start_sec, end_sec, speaker_label, text, words_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [_segment_row(meeting_id, segment) for segment in transcript.segments],
        )
    return get_transcript(connection, meeting_id)


def get_transcript(connection: sqlite3.Connection, meeting_id: str) -> Transcript:
    meeting = connection.execute(
        "SELECT transcript_revision FROM meetings WHERE id = ?", (meeting_id,)
    ).fetchone()
    if meeting is None:
        raise NotFoundError(f"Không tìm thấy cuộc họp {meeting_id}")
    rows = connection.execute(
        """
        SELECT s.id, s.start_sec, s.end_sec, s.speaker_label, sp.name AS speaker_name,
               s.text, s.words_json
        FROM segments s
        JOIN meeting_speakers ms
          ON ms.meeting_id = s.meeting_id AND ms.speaker_label = s.speaker_label
        LEFT JOIN speakers sp ON sp.id = ms.speaker_id
        WHERE s.meeting_id = ?
        ORDER BY s.start_sec, s.id
        """,
        (meeting_id,),
    ).fetchall()
    return Transcript(
        meeting_id=meeting_id,
        revision=meeting["transcript_revision"],
        segments=[_segment_from_row(row) for row in rows],
    )


def list_meeting_speakers(connection: sqlite3.Connection, meeting_id: str) -> list[MeetingSpeaker]:
    _require_meeting(connection, meeting_id)
    rows = connection.execute(
        """
        SELECT ms.speaker_label, ms.speaker_id, sp.name AS speaker_name,
               ms.match_score, ms.confirmed_at
        FROM meeting_speakers ms
        LEFT JOIN speakers sp ON sp.id = ms.speaker_id
        WHERE ms.meeting_id = ?
        ORDER BY ms.speaker_label
        """,
        (meeting_id,),
    ).fetchall()
    return [MeetingSpeaker.model_validate(dict(row)) for row in rows]


def confirm_speaker(connection: sqlite3.Connection, confirmation: SpeakerConfirmation) -> bool:
    """Gán tên thật cho một nhãn. Trả False khi xác nhận này đã được lưu trước đó."""
    with write_transaction(connection):
        mapping = connection.execute(
            "SELECT speaker_id, confirmed_at FROM meeting_speakers"
            " WHERE meeting_id = ? AND speaker_label = ?",
            (confirmation.meeting_id, confirmation.speaker_label),
        ).fetchone()
        if mapping is None:
            raise NotFoundError(
                f"Cuộc họp {confirmation.meeting_id} không có nhãn {confirmation.speaker_label}"
            )
        speaker_id = _get_or_create_speaker(connection, confirmation.name)
        if mapping["confirmed_at"] is not None and mapping["speaker_id"] == speaker_id:
            return False
        if confirmation.embedding is not None:
            _save_voice_profile(connection, speaker_id, confirmation.embedding)
        connection.execute(
            f"UPDATE meeting_speakers SET speaker_id = ?, confirmed_at = {SQL_NOW}"
            " WHERE meeting_id = ? AND speaker_label = ?",
            (speaker_id, confirmation.meeting_id, confirmation.speaker_label),
        )
    return True


def list_speakers(connection: sqlite3.Connection) -> list[Speaker]:
    rows = connection.execute("SELECT * FROM speakers ORDER BY name").fetchall()
    return [Speaker.model_validate(dict(row)) for row in rows]


def rename_speaker(connection: sqlite3.Connection, speaker_id: int, name: str) -> Speaker:
    try:
        with write_transaction(connection):
            updated = connection.execute(
                f"UPDATE speakers SET name = ?, updated_at = {SQL_NOW} WHERE id = ?",
                (normalize_person_name(name), speaker_id),
            ).rowcount
    except sqlite3.IntegrityError as error:
        raise ConflictError(f"Đã có người tên {name} trong danh bạ") from error
    if updated == 0:
        raise NotFoundError(f"Không tìm thấy người nói {speaker_id}")
    return _get_speaker(connection, speaker_id)


def delete_speaker(connection: sqlite3.Connection, speaker_id: int) -> None:
    """Các nhãn từng gán cho người này trở về chưa xác nhận để có thể gán lại."""
    with write_transaction(connection):
        connection.execute(
            "UPDATE meeting_speakers SET confirmed_at = NULL WHERE speaker_id = ?", (speaker_id,)
        )
        deleted = connection.execute("DELETE FROM speakers WHERE id = ?", (speaker_id,)).rowcount
        if deleted == 0:
            raise NotFoundError(f"Không tìm thấy người nói {speaker_id}")


def find_closest_speakers(
    connection: sqlite3.Connection, embedding: VoiceEmbedding, limit: int = DEFAULT_MATCH_LIMIT
) -> list[SpeakerMatch]:
    """Chỉ so với vector của cùng phiên bản model."""
    rows = connection.execute(
        """
        SELECT s.id AS speaker_id, s.name,
               1 - vec_distance_cosine(v.embedding, ?) AS similarity
        FROM voice_profiles v
        JOIN speakers s ON s.id = v.speaker_id
        WHERE v.model_version = ?
        ORDER BY similarity DESC
        LIMIT ?
        """,
        (sqlite_vec.serialize_float32(embedding.values), embedding.model_version, limit),
    ).fetchall()
    return [SpeakerMatch.model_validate(dict(row)) for row in rows]


def save_report(connection: sqlite3.Connection, draft: ReportDraft, expected_revision: int | None) -> Report:
    """Chỉ lưu khi transcript và biên bản hiện tại vẫn là bản mà draft được tạo từ đó.

    expected_revision là revision của biên bản lúc bắt đầu (None nếu khi đó chưa có biên bản).
    """
    with write_transaction(connection):
        meeting = connection.execute(
            "SELECT transcript_revision FROM meetings WHERE id = ?", (draft.meeting_id,)
        ).fetchone()
        if meeting is None:
            raise NotFoundError(f"Không tìm thấy cuộc họp {draft.meeting_id}")
        if meeting["transcript_revision"] != draft.transcript_revision:
            raise ConflictError("Transcript đã thay đổi trong lúc tạo biên bản, hãy tạo lại")
        current = connection.execute(
            "SELECT revision FROM reports WHERE meeting_id = ?", (draft.meeting_id,)
        ).fetchone()
        current_revision = current["revision"] if current is not None else None
        if current_revision != expected_revision:
            raise ConflictError("Biên bản vừa được sửa ở nơi khác, hãy tải lại rồi thử lại")
        connection.execute(
            f"""
            INSERT INTO reports (meeting_id, content_json, warnings_json, source, llm_model,
                                 prompt_version, transcript_revision, revision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (meeting_id) DO UPDATE SET
                content_json = excluded.content_json,
                warnings_json = excluded.warnings_json,
                source = excluded.source,
                llm_model = excluded.llm_model,
                prompt_version = excluded.prompt_version,
                transcript_revision = excluded.transcript_revision,
                revision = excluded.revision,
                updated_at = {SQL_NOW}
            """,
            (
                draft.meeting_id,
                draft.content.model_dump_json(),
                json.dumps(draft.warnings, ensure_ascii=False),
                draft.source,
                draft.llm_model,
                draft.prompt_version,
                draft.transcript_revision,
                (current_revision or 0) + 1,
            ),
        )
    return get_report(connection, draft.meeting_id)


def find_report(connection: sqlite3.Connection, meeting_id: str) -> Report | None:
    row = connection.execute(
        """
        SELECT r.*, m.transcript_revision AS current_transcript_revision
        FROM reports r JOIN meetings m ON m.id = r.meeting_id
        WHERE r.meeting_id = ?
        """,
        (meeting_id,),
    ).fetchone()
    if row is None:
        return None
    return Report(
        meeting_id=row["meeting_id"],
        transcript_revision=row["transcript_revision"],
        content=json.loads(row["content_json"]),
        warnings=json.loads(row["warnings_json"]),
        source=row["source"],
        llm_model=row["llm_model"],
        prompt_version=row["prompt_version"],
        revision=row["revision"],
        stale=row["transcript_revision"] != row["current_transcript_revision"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_report(connection: sqlite3.Connection, meeting_id: str) -> Report:
    report = find_report(connection, meeting_id)
    if report is None:
        raise NotFoundError(f"Cuộc họp {meeting_id} chưa có biên bản")
    return report


def _require_meeting(connection: sqlite3.Connection, meeting_id: str) -> None:
    if connection.execute("SELECT 1 FROM meetings WHERE id = ?", (meeting_id,)).fetchone() is None:
        raise NotFoundError(f"Không tìm thấy cuộc họp {meeting_id}")


def _speaker_names_by_label(segments: list[TranscriptSegmentIn]) -> dict[str, str | None]:
    names: dict[str, str | None] = {}
    for segment in segments:
        if names.get(segment.speaker_label) is None:
            names[segment.speaker_label] = _clean_name(segment.speaker_name)
    return names


def _clean_name(name: str | None) -> str | None:
    if name is None or not name.strip():
        return None
    return normalize_person_name(name)


def _remove_stale_labels(connection: sqlite3.Connection, meeting_id: str, labels: set[str]) -> None:
    existing = connection.execute(
        "SELECT speaker_label FROM meeting_speakers WHERE meeting_id = ?", (meeting_id,)
    ).fetchall()
    stale = [(meeting_id, row["speaker_label"]) for row in existing if row["speaker_label"] not in labels]
    connection.executemany(
        "DELETE FROM meeting_speakers WHERE meeting_id = ? AND speaker_label = ?", stale
    )


def _segment_row(meeting_id: str, segment: TranscriptSegmentIn) -> tuple:
    words_json = None
    if segment.words is not None:
        words_json = json.dumps([word.model_dump() for word in segment.words], ensure_ascii=False)
    return (meeting_id, segment.start, segment.end, segment.speaker_label, segment.text, words_json)


def _segment_from_row(row: sqlite3.Row) -> Segment:
    words = json.loads(row["words_json"]) if row["words_json"] is not None else None
    return Segment(
        id=row["id"],
        start_sec=row["start_sec"],
        end_sec=row["end_sec"],
        speaker_label=row["speaker_label"],
        speaker_name=row["speaker_name"],
        text=row["text"],
        words=words,
    )


def _get_or_create_speaker(connection: sqlite3.Connection, name: str) -> int:
    connection.execute("INSERT INTO speakers (name) VALUES (?) ON CONFLICT (name) DO NOTHING", (name,))
    return connection.execute("SELECT id FROM speakers WHERE name = ?", (name,)).fetchone()["id"]


def _get_speaker(connection: sqlite3.Connection, speaker_id: int) -> Speaker:
    row = connection.execute("SELECT * FROM speakers WHERE id = ?", (speaker_id,)).fetchone()
    return Speaker.model_validate(dict(row))


def _save_voice_profile(
    connection: sqlite3.Connection, speaker_id: int, embedding: VoiceEmbedding
) -> None:
    """Người dùng xác nhận: thêm 1 sample 'manual', tính lại hồ sơ (trung bình có trọng số,
    không ghi đè) và bật lại tự học nếu speech_ai đã tạm dừng vì phát hiện lệch."""
    voice_profiles.add_sample(
        connection, speaker_id, embedding.model_version, embedding.values, source="manual"
    )
    voice_profiles.recompute_profile(connection, speaker_id, embedding.model_version)
    voice_profiles.set_auto_learn(connection, speaker_id, embedding.model_version, enabled=True)
