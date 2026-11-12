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
    Transcript,
    TranscriptIn,
    TranscriptSegmentIn,
    VoiceprintSummary,
    normalize_person_name,
)

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
    """Thay toàn bộ transcript và tăng transcript_revision, nên biên bản cũ thành stale.

    Nhãn SPEAKER_xx không ổn định giữa các lần chạy tách giọng, nên mọi xác nhận tên cũ của cuộc họp bị bỏ,
    kể cả mẫu giọng đã học từ các xác nhận đó. Tên được gán lại theo kết quả so khớp danh bạ
    (speakers[].name) mà speech_ai gửi kèm; người dùng xác nhận lại thì mẫu giọng được học lại.
    """
    meeting_id = transcript.meeting_id
    with write_transaction(connection):
        bumped = connection.execute(
            "UPDATE meetings SET transcript_revision = transcript_revision + 1 WHERE id = ?", (meeting_id,)
        ).rowcount
        if bumped == 0:
            raise NotFoundError(f"Không tìm thấy cuộc họp {meeting_id}")
        _forget_confirmed_voices(connection, meeting_id)
        connection.execute("DELETE FROM segments WHERE meeting_id = ?", (meeting_id,))
        connection.execute("DELETE FROM meeting_speakers WHERE meeting_id = ?", (meeting_id,))
        connection.executemany(
            """
            INSERT INTO meeting_speakers (meeting_id, speaker_label, speaker_id, match_score,
                                          channel, duration_sec, embedding, embedding_model)
            VALUES (:meeting_id, :label, :speaker_id, :match_score,
                    :channel, :duration_sec, :embedding, :embedding_model)
            """,
            _meeting_speaker_rows(connection, transcript),
        )
        connection.executemany(
            "INSERT INTO segments (meeting_id, start_sec, end_sec, speaker_label, text, words_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [_segment_row(meeting_id, segment) for segment in transcript.segments],
        )
    return get_transcript(connection, meeting_id)


def get_transcript(connection: sqlite3.Connection, meeting_id: str) -> Transcript:
    """Đọc revision trước các câu: nếu transcript bị thay giữa hai lệnh đọc thì kết quả mang revision cũ,
    nên biên bản tạo từ nó bị từ chối hoặc thành stale chứ không bị coi nhầm là mới."""
    revision = _current_transcript_revision(connection, meeting_id)
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
    return Transcript(meeting_id=meeting_id, revision=revision, segments=[_segment_from_row(row) for row in rows])


def list_meeting_speakers(connection: sqlite3.Connection, meeting_id: str) -> list[MeetingSpeaker]:
    _current_transcript_revision(connection, meeting_id)
    rows = connection.execute(
        """
        SELECT ms.speaker_label, ms.speaker_id, sp.name AS speaker_name, ms.channel,
               ms.duration_sec, ms.match_score, ms.embedding IS NOT NULL AS has_meeting_embedding,
               ms.confirmed_at
        FROM meeting_speakers ms
        LEFT JOIN speakers sp ON sp.id = ms.speaker_id
        WHERE ms.meeting_id = ?
        ORDER BY ms.speaker_label
        """,
        (meeting_id,),
    ).fetchall()
    return [MeetingSpeaker.model_validate(dict(row)) for row in rows]


def confirm_speaker(connection: sqlite3.Connection, confirmation: SpeakerConfirmation) -> bool:
    """Gán tên thật cho một nhãn. Trả False khi xác nhận này đã được lưu trước đó.

    Vector của nhãn thành mẫu 'manual' của người được xác nhận; sửa nhãn sang người khác thì mẫu chuyển theo.
    Xác nhận cũng bật lại tự học của speech_ai cho người đó. transcript_revision chỉ tăng khi tên hiển thị
    của nhãn đổi, để xác nhận một tên máy đã gán đúng không làm biên bản thành stale.
    """
    label = (confirmation.meeting_id, confirmation.speaker_label)
    with write_transaction(connection):
        mapping = connection.execute(
            "SELECT speaker_id, confirmed_at, embedding_model FROM meeting_speakers"
            " WHERE meeting_id = ? AND speaker_label = ?",
            label,
        ).fetchone()
        if mapping is None:
            raise NotFoundError(
                f"Cuộc họp {confirmation.meeting_id} không có nhãn {confirmation.speaker_label}"
            )
        speaker_id = _get_or_create_speaker(connection, confirmation.name)
        name_changes = mapping["speaker_id"] != speaker_id
        newly_confirmed = mapping["confirmed_at"] is None or name_changes
        if newly_confirmed:
            _move_voice_sample(connection, confirmation, speaker_id)
            connection.execute(
                f"UPDATE meeting_speakers SET speaker_id = ?, confirmed_at = {SQL_NOW}"
                " WHERE meeting_id = ? AND speaker_label = ?",
                (speaker_id, *label),
            )
        if name_changes:
            connection.execute(
                "UPDATE meetings SET transcript_revision = transcript_revision + 1 WHERE id = ?",
                (confirmation.meeting_id,),
            )
        if mapping["embedding_model"] is not None:
            voice_profiles.set_auto_learn(connection, speaker_id, mapping["embedding_model"], enabled=True)
    return newly_confirmed


def list_speakers(connection: sqlite3.Connection) -> list[Speaker]:
    return _load_speakers(connection, "", ())


def rename_speaker(connection: sqlite3.Connection, speaker_id: int, name: str) -> Speaker:
    """Tên không được trùng người khác kể cả khi chỉ khác chữ hoa; các cuộc họp có người này thành stale."""
    name = normalize_person_name(name)
    with write_transaction(connection):
        if connection.execute("SELECT 1 FROM speakers WHERE id = ?", (speaker_id,)).fetchone() is None:
            raise NotFoundError(f"Không tìm thấy người nói {speaker_id}")
        if _find_speaker_id_by_name(connection, name) not in (None, speaker_id):
            raise ConflictError(f"Đã có người tên {name} trong danh bạ")
        connection.execute(
            f"UPDATE speakers SET name = ?, updated_at = {SQL_NOW} WHERE id = ?", (name, speaker_id)
        )
        _mark_meetings_of_speaker_changed(connection, speaker_id)
    return _get_speaker(connection, speaker_id)


def delete_speaker(connection: sqlite3.Connection, speaker_id: int) -> None:
    """Xóa người, mẫu giọng và vân tay; các nhãn từng gán cho người này trở về chưa xác nhận."""
    with write_transaction(connection):
        _mark_meetings_of_speaker_changed(connection, speaker_id)
        connection.execute(
            "UPDATE meeting_speakers SET confirmed_at = NULL WHERE speaker_id = ?", (speaker_id,)
        )
        deleted = connection.execute("DELETE FROM speakers WHERE id = ?", (speaker_id,)).rowcount
        if deleted == 0:
            raise NotFoundError(f"Không tìm thấy người nói {speaker_id}")


def save_generated_report(
    connection: sqlite3.Connection, draft: ReportDraft, expected_revision: int | None
) -> Report:
    """Biên bản do LLM tạo chỉ được lưu khi transcript (kể cả tên) không đổi trong lúc chờ LLM."""
    with write_transaction(connection):
        if _current_transcript_revision(connection, draft.meeting_id) != draft.transcript_revision:
            raise ConflictError("Transcript đã thay đổi trong lúc tạo biên bản, hãy tạo lại")
        _write_report(connection, draft, expected_revision)
    return get_report(connection, draft.meeting_id)


def save_edited_report(
    connection: sqlite3.Connection, draft: ReportDraft, expected_revision: int | None
) -> Report:
    """Bản người dùng sửa giữ transcript_revision mà họ đã đối chiếu, nên biên bản cũ vẫn có thể stale."""
    with write_transaction(connection):
        if draft.transcript_revision > _current_transcript_revision(connection, draft.meeting_id):
            raise ConflictError("Phiên bản transcript gửi lên không tồn tại")
        _write_report(connection, draft, expected_revision)
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


def _current_transcript_revision(connection: sqlite3.Connection, meeting_id: str) -> int:
    row = connection.execute("SELECT transcript_revision FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Không tìm thấy cuộc họp {meeting_id}")
    return row["transcript_revision"]


def _mark_meetings_of_speaker_changed(connection: sqlite3.Connection, speaker_id: int) -> None:
    connection.execute(
        "UPDATE meetings SET transcript_revision = transcript_revision + 1"
        " WHERE id IN (SELECT meeting_id FROM meeting_speakers WHERE speaker_id = ?)",
        (speaker_id,),
    )


def _write_report(connection: sqlite3.Connection, draft: ReportDraft, expected_revision: int | None) -> None:
    """expected_revision là revision của biên bản mà người gửi đã đọc (None nếu khi đó chưa có biên bản)."""
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


def _meeting_speaker_rows(connection: sqlite3.Connection, transcript: TranscriptIn) -> list[dict[str, object]]:
    """Một dòng meeting_speakers cho mỗi nhãn xuất hiện trong segments hoặc speakers[].

    Tên khớp được ưu tiên; speaker_id chỉ được dùng khi không có tên, vì id có thể đến từ danh bạ khác.
    """
    segment_names = _speaker_names_by_label(transcript.segments)
    details = {speaker.label: speaker for speaker in transcript.speakers}
    rows: list[dict[str, object]] = []
    for label in dict.fromkeys([*segment_names, *details]):
        speaker = details.get(label)
        name = (_clean_name(speaker.name) if speaker else None) or segment_names.get(label)
        rows.append({
            "meeting_id": transcript.meeting_id,
            "label": label,
            "speaker_id": _resolve_speaker_id(connection, name, speaker.speaker_id if speaker else None),
            "match_score": speaker.match_score if speaker else None,
            "channel": speaker.channel if speaker else None,
            "duration_sec": speaker.duration_sec if speaker else None,
            "embedding": sqlite_vec.serialize_float32(speaker.embedding) if speaker and speaker.embedding else None,
            "embedding_model": speaker.embedding_model if speaker else None,
        })
    return rows


def _resolve_speaker_id(connection: sqlite3.Connection, name: str | None, book_id: str | None) -> int | None:
    if name is not None:
        return _find_speaker_id_by_name(connection, name)
    parsed = _parse_book_id(book_id)
    if parsed is None:
        return None
    row = connection.execute("SELECT id FROM speakers WHERE id = ?", (parsed,)).fetchone()
    return row["id"] if row is not None else None


def _parse_book_id(value: str | None) -> int | None:
    """speaker_id của danh bạ là chuỗi chữ số ASCII; mọi dạng khác không phải id của DB này."""
    if value is None or not (value.isascii() and value.isdigit()):
        return None
    return int(value)


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


def _find_speaker_id_by_name(connection: sqlite3.Connection, name: str) -> int | None:
    """So tên không phân biệt hoa thường; tên trong DB luôn đã chuẩn hóa NFC."""
    wanted = name.casefold()
    for row in connection.execute("SELECT id, name FROM speakers"):
        if row["name"].casefold() == wanted:
            return row["id"]
    return None


def _get_or_create_speaker(connection: sqlite3.Connection, name: str) -> int:
    existing = _find_speaker_id_by_name(connection, name)
    if existing is not None:
        return existing
    return connection.execute("INSERT INTO speakers (name) VALUES (?)", (name,)).lastrowid


def _get_speaker(connection: sqlite3.Connection, speaker_id: int) -> Speaker:
    return _load_speakers(connection, "WHERE s.id = ?", (speaker_id,))[0]


def _load_speakers(connection: sqlite3.Connection, where: str, params: tuple) -> list[Speaker]:
    """`where` là mệnh đề cố định trong module này (không nhận chuỗi từ bên ngoài), lọc theo bảng `s`."""
    profiles: dict[int, list[VoiceprintSummary]] = {}
    for row in connection.execute(
        "SELECT v.speaker_id, v.model_version, v.total_sec, v.auto_learn, v.paused_reason, v.updated_at"
        f" FROM voice_profiles v JOIN speakers s ON s.id = v.speaker_id {where} ORDER BY v.model_version",
        params,
    ):
        profiles.setdefault(row["speaker_id"], []).append(VoiceprintSummary.model_validate(dict(row)))
    rows = connection.execute(f"SELECT s.* FROM speakers s {where} ORDER BY s.name", params).fetchall()
    return [Speaker.model_validate({**dict(row), "voiceprints": profiles.get(row["id"], [])}) for row in rows]


# Cosine từ mức này trở lên coi là cùng một giọng; bằng ngưỡng nhận người DEFAULT_THRESHOLD của speech_ai.
SAME_VOICE_MIN_SIMILARITY = 0.55
_MEETING_CONFIRMED_SAMPLES = "source = 'manual' AND meeting_id = :meeting_id"
_CONFIRMED_SAMPLE = f"{_MEETING_CONFIRMED_SAMPLES} AND speaker_label = :speaker_label"
_SAME_VOICE_AUTO_SAMPLE = """
    source = 'auto' AND meeting_id = :meeting_id AND :same_voice <= (
        SELECT CASE WHEN ms.embedding IS NOT NULL AND ms.embedding_model = voice_samples.model_version
                    THEN 1 - vec_distance_cosine(ms.embedding, voice_samples.embedding) END
        FROM meeting_speakers ms
        WHERE ms.meeting_id = :meeting_id AND ms.speaker_label = :speaker_label
    )
"""


def _move_voice_sample(
    connection: sqlite3.Connection, confirmation: SpeakerConfirmation, speaker_id: int
) -> None:
    """Sau khi nhãn được xác nhận là `speaker_id`: mẫu 'manual' của nhãn thuộc về người đó, và mẫu máy tự học
    từ cùng giọng trong cuộc họp này chỉ còn tính cho người đó.

    Mẫu tự học được tìm theo độ giống giọng chứ không theo nhãn, vì nhãn SPEAKER_xx đổi giữa các lần chạy
    pipeline. Mẫu của người khác thành 'suspect' thay vì bị xóa, để hạn mức tự học của cuộc họp vẫn tính.
    """
    params = {
        "meeting_id": confirmation.meeting_id,
        "speaker_label": confirmation.speaker_label,
        "speaker_id": speaker_id,
        "same_voice": SAME_VOICE_MIN_SIMILARITY,
    }
    affected = _sample_owners(connection, f"({_CONFIRMED_SAMPLE}) OR ({_SAME_VOICE_AUTO_SAMPLE})", params)
    connection.execute(f"DELETE FROM voice_samples WHERE {_CONFIRMED_SAMPLE}", params)
    connection.execute(
        "UPDATE voice_samples SET status = CASE WHEN speaker_id = :speaker_id THEN 'active' ELSE 'suspect' END"
        f" WHERE {_SAME_VOICE_AUTO_SAMPLE}",
        params,
    )
    connection.execute(
        """
        INSERT INTO voice_samples
            (speaker_id, model_version, embedding, duration_sec, source, meeting_id, speaker_label)
        SELECT :speaker_id, embedding_model, embedding, COALESCE(duration_sec, 0), 'manual',
               meeting_id, speaker_label
        FROM meeting_speakers
        WHERE meeting_id = :meeting_id AND speaker_label = :speaker_label AND embedding IS NOT NULL
        """,
        params,
    )
    affected |= _sample_owners(connection, _CONFIRMED_SAMPLE, params)
    _recompute_profiles(connection, affected)


def _forget_confirmed_voices(connection: sqlite3.Connection, meeting_id: str) -> None:
    """Bỏ các mẫu 'manual' học từ những xác nhận tên của cuộc họp, rồi tính lại hồ sơ của người có mẫu bị bỏ."""
    params = {"meeting_id": meeting_id}
    affected = _sample_owners(connection, _MEETING_CONFIRMED_SAMPLES, params)
    connection.execute(f"DELETE FROM voice_samples WHERE {_MEETING_CONFIRMED_SAMPLES}", params)
    _recompute_profiles(connection, affected)


def _sample_owners(connection: sqlite3.Connection, where: str, params: dict[str, object]) -> set[tuple[int, str]]:
    """`where` là một trong các mệnh đề cố định ở trên, không nhận chuỗi từ bên ngoài."""
    rows = connection.execute(f"SELECT DISTINCT speaker_id, model_version FROM voice_samples WHERE {where}", params)
    return {(row["speaker_id"], row["model_version"]) for row in rows}


def _recompute_profiles(connection: sqlite3.Connection, owners: set[tuple[int, str]]) -> None:
    for speaker_id, model_version in owners:
        voice_profiles.recompute_profile(connection, speaker_id, model_version)
