"""Bảng SQLite và kiểu dữ liệu dùng chung: Meetings, Segments, Speakers, Jobs, Reports."""
import unicodedata
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated

import numpy as np
from pydantic import AfterValidator, BaseModel, Field, FiniteFloat, model_validator

EMBEDDING_DIM = 192
MAX_SEGMENTS = 100_000
MAX_SEGMENT_TEXT_CHARS = 10_000
# Nhãn do bộ tách giọng đặt (SPEAKER_00, SPEAKER_UNKNOWN...). Không cho khoảng trắng hay ký tự điều khiển,
# vì nhãn được in nguyên văn vào transcript gửi LLM và vào file Word.
SPEAKER_LABEL_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

SQL_NOW = "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"

_SCHEMA_V1 = f"""
CREATE TABLE meetings (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    audio_path   TEXT,
    started_at   TEXT NOT NULL,
    duration_sec REAL CHECK (duration_sec IS NULL OR duration_sec >= 0),
    capture_mode TEXT CHECK (capture_mode IN ('headset', 'room')),
    status       TEXT NOT NULL CHECK (status IN ('recording', 'recorded', 'failed')),
    created_at   TEXT NOT NULL DEFAULT {SQL_NOW}
);

CREATE TABLE speakers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT {SQL_NOW},
    updated_at TEXT NOT NULL DEFAULT {SQL_NOW}
);

CREATE TABLE voice_profiles (
    speaker_id    INTEGER NOT NULL REFERENCES speakers(id) ON DELETE CASCADE,
    model_version TEXT NOT NULL,
    embedding     BLOB NOT NULL CHECK (length(embedding) = {EMBEDDING_DIM * 4}),
    sample_count  INTEGER NOT NULL DEFAULT 1 CHECK (sample_count >= 1),
    updated_at    TEXT NOT NULL DEFAULT {SQL_NOW},
    PRIMARY KEY (speaker_id, model_version)
);

CREATE TABLE meeting_speakers (
    meeting_id    TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    speaker_label TEXT NOT NULL,
    speaker_id    INTEGER REFERENCES speakers(id) ON DELETE SET NULL,
    match_score   REAL,
    confirmed_at  TEXT,
    PRIMARY KEY (meeting_id, speaker_label)
);

CREATE TABLE segments (
    id            INTEGER PRIMARY KEY,
    meeting_id    TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    start_sec     REAL NOT NULL CHECK (start_sec >= 0),
    end_sec       REAL NOT NULL,
    speaker_label TEXT NOT NULL,
    text          TEXT NOT NULL,
    words_json    TEXT,
    CHECK (end_sec >= start_sec),
    FOREIGN KEY (meeting_id, speaker_label)
        REFERENCES meeting_speakers(meeting_id, speaker_label) ON DELETE CASCADE
);
CREATE INDEX idx_segments_meeting_start ON segments(meeting_id, start_sec);

CREATE TABLE jobs (
    id           INTEGER PRIMARY KEY,
    meeting_id   TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('transcribe', 'report')),
    provider     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN
                     ('queued', 'waiting_network', 'running', 'succeeded', 'failed', 'cancelled')),
    stage        TEXT,
    progress     REAL NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
    attempts     INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    timings_json TEXT,
    created_at   TEXT NOT NULL DEFAULT {SQL_NOW},
    started_at   TEXT,
    finished_at  TEXT
);
CREATE UNIQUE INDEX uq_jobs_one_active ON jobs(meeting_id, kind)
    WHERE status IN ('queued', 'waiting_network', 'running');

CREATE TABLE reports (
    meeting_id     TEXT PRIMARY KEY REFERENCES meetings(id) ON DELETE CASCADE,
    content_json   TEXT NOT NULL,
    warnings_json  TEXT NOT NULL DEFAULT '[]',
    source         TEXT NOT NULL CHECK (source IN ('llm', 'manual')),
    llm_model      TEXT,
    prompt_version TEXT,
    created_at     TEXT NOT NULL DEFAULT {SQL_NOW},
    updated_at     TEXT NOT NULL DEFAULT {SQL_NOW}
);
"""

_SCHEMA_V2 = """
ALTER TABLE meetings ADD COLUMN transcript_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE reports ADD COLUMN transcript_revision INTEGER NOT NULL DEFAULT 0;
"""

# v3: lưu từng sample vân tay giọng để speech_ai tự học (ghi thẳng) có kiểm soát.
# voice_profiles.embedding = trung bình có trọng số của các sample 'active'.
_SCHEMA_V3 = f"""
CREATE TABLE voice_samples (
    id            INTEGER PRIMARY KEY,
    speaker_id    INTEGER NOT NULL REFERENCES speakers(id) ON DELETE CASCADE,
    model_version TEXT NOT NULL,
    embedding     BLOB NOT NULL CHECK (length(embedding) = {EMBEDDING_DIM * 4}),
    duration_sec  REAL NOT NULL DEFAULT 0 CHECK (duration_sec >= 0),
    source        TEXT NOT NULL CHECK (source IN ('auto', 'manual')),
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspect')),
    meeting_id    TEXT,
    speaker_label TEXT,
    match_score   REAL,
    created_at    TEXT NOT NULL DEFAULT {SQL_NOW}
);
CREATE INDEX idx_voice_samples_speaker ON voice_samples(speaker_id, model_version, status);
CREATE INDEX idx_voice_samples_meeting ON voice_samples(meeting_id, speaker_id);

ALTER TABLE voice_profiles ADD COLUMN total_sec REAL NOT NULL DEFAULT 0;
ALTER TABLE voice_profiles ADD COLUMN auto_learn TEXT NOT NULL DEFAULT 'on'
    CHECK (auto_learn IN ('on', 'paused'));
ALTER TABLE voice_profiles ADD COLUMN paused_reason TEXT;
ALTER TABLE voice_profiles ADD COLUMN auto_meetings_since_check INTEGER NOT NULL DEFAULT 0;

-- Vector cũ (từ /speakers/confirm) thành 1 sample 'manual'
INSERT INTO voice_samples (speaker_id, model_version, embedding, source)
    SELECT speaker_id, model_version, embedding, 'manual' FROM voice_profiles;
"""

# v4: transcript kèm vector giọng của từng nhãn. Mỗi nhãn đã xác nhận có đúng một mẫu 'manual',
# để sửa nhãn sang người khác thì gỡ được mẫu khỏi người cũ.
_SCHEMA_V4 = f"""
ALTER TABLE meeting_speakers ADD COLUMN channel TEXT CHECK (channel IN ('mic', 'system', 'mono'));
ALTER TABLE meeting_speakers ADD COLUMN duration_sec REAL CHECK (duration_sec IS NULL OR duration_sec >= 0);
ALTER TABLE meeting_speakers ADD COLUMN embedding BLOB
    CHECK (embedding IS NULL OR length(embedding) = {EMBEDDING_DIM * 4});
ALTER TABLE meeting_speakers ADD COLUMN embedding_model TEXT;
CREATE UNIQUE INDEX uq_voice_samples_confirmation ON voice_samples(meeting_id, speaker_label)
    WHERE source = 'manual' AND meeting_id IS NOT NULL;
"""

MIGRATIONS: dict[int, str] = {1: _SCHEMA_V1, 2: _SCHEMA_V2, 3: _SCHEMA_V3, 4: _SCHEMA_V4}
SCHEMA_VERSION = max(MIGRATIONS)


def normalize_person_name(name: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFC", name).split())
    if not normalized:
        raise ValueError("Tên không được để trống")
    return normalized


def require_usable_embedding(values: Sequence[float]) -> None:
    """Vân tay giọng phải đủ số chiều và dùng được sau khi lưu dạng float32 (hữu hạn, khác vector 0)."""
    if len(values) != EMBEDDING_DIM:
        raise ValueError(f"Vector giọng có {len(values)} chiều, cần {EMBEDDING_DIM}")
    with np.errstate(over="ignore"):
        stored = np.asarray(values, dtype=np.float64).astype(np.float32)
    if not np.all(np.isfinite(stored)):
        raise ValueError("Vector giọng có giá trị NaN, vô cực hoặc vượt giới hạn float32")
    if not np.any(stored):
        raise ValueError("Vector giọng toàn số 0, không so khớp được")


PersonName = Annotated[str, AfterValidator(normalize_person_name)]
SpeakerLabel = Annotated[str, Field(pattern=SPEAKER_LABEL_PATTERN)]


class MeetingStatus(StrEnum):
    RECORDING = "recording"
    RECORDED = "recorded"
    FAILED = "failed"


class CaptureMode(StrEnum):
    HEADSET = "headset"
    ROOM = "room"


class JobKind(StrEnum):
    TRANSCRIBE = "transcribe"
    REPORT = "report"


class JobStatus(StrEnum):
    QUEUED = "queued"
    WAITING_NETWORK = "waiting_network"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReportSource(StrEnum):
    LLM = "llm"
    MANUAL = "manual"


class AutoLearn(StrEnum):
    ON = "on"
    PAUSED = "paused"


class SpeakerChannel(StrEnum):
    MIC = "mic"
    SYSTEM = "system"
    MONO = "mono"


class Meeting(BaseModel):
    id: str
    title: str
    audio_path: str | None
    started_at: datetime
    duration_sec: float | None
    capture_mode: CaptureMode | None
    status: MeetingStatus
    created_at: datetime


def _require_ordered(start: float, end: float) -> None:
    if end < start:
        raise ValueError(f"end ({end}) nhỏ hơn start ({start})")


class Word(BaseModel):
    word: str
    start: FiniteFloat = Field(ge=0)
    end: FiniteFloat

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "Word":
        _require_ordered(self.start, self.end)
        return self


class TranscriptSegmentIn(BaseModel):
    """Một câu theo shared/schemas/transcript_contract.json."""

    start: FiniteFloat = Field(ge=0)
    end: FiniteFloat
    speaker_label: SpeakerLabel
    speaker_name: str | None = None
    text: str = Field(max_length=MAX_SEGMENT_TEXT_CHARS)
    words: list[Word] | None = None

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "TranscriptSegmentIn":
        _require_ordered(self.start, self.end)
        return self


class TranscriptSpeakerIn(BaseModel):
    """Một người nói trong `speakers[]` của transcript_contract.json, kèm vân tay để enroll."""

    label: SpeakerLabel
    channel: SpeakerChannel
    speaker_id: str | None = None
    name: str | None
    match_score: FiniteFloat | None = None
    duration_sec: FiniteFloat | None = Field(default=None, ge=0)
    embedding_model: str = Field(min_length=1)
    embedding: list[FiniteFloat] | None

    @model_validator(mode="after")
    def _embedding_usable(self) -> "TranscriptSpeakerIn":
        if self.embedding is not None:
            require_usable_embedding(self.embedding)
        return self


class TranscriptIn(BaseModel):
    """Transcript do speech_ai (TV2) trả về. `speakers` có thể vắng với transcript kiểu cũ."""

    meeting_id: str
    language: str | None = None
    speakers: list[TranscriptSpeakerIn] = Field(default_factory=list)
    segments: list[TranscriptSegmentIn] = Field(max_length=MAX_SEGMENTS)

    @model_validator(mode="after")
    def _speaker_labels_unique(self) -> "TranscriptIn":
        labels = [speaker.label for speaker in self.speakers]
        if len(labels) != len(set(labels)):
            raise ValueError("speakers[] có nhãn bị lặp")
        return self


class Segment(BaseModel):
    id: int
    start_sec: float
    end_sec: float
    speaker_label: str
    speaker_name: str | None
    text: str
    words: list[Word] | None


class Transcript(BaseModel):
    meeting_id: str
    revision: int
    segments: list[Segment]


class VoiceprintSummary(BaseModel):
    model_version: str
    total_sec: float
    auto_learn: AutoLearn
    paused_reason: str | None = Field(
        description="Lý do speech_ai tạm dừng tự học giọng người này; xác nhận lại tên của họ để bật lại"
    )
    updated_at: datetime


class Speaker(BaseModel):
    id: int
    name: str
    voiceprints: list[VoiceprintSummary]
    created_at: datetime
    updated_at: datetime


class MeetingSpeaker(BaseModel):
    speaker_label: str
    speaker_id: int | None
    speaker_name: str | None
    channel: SpeakerChannel | None
    duration_sec: float | None
    match_score: float | None
    has_meeting_embedding: bool = Field(description="Cuộc họp có vector giọng của nhãn này để enroll")
    confirmed_at: datetime | None


class SpeakerConfirmation(BaseModel):
    meeting_id: str
    speaker_label: SpeakerLabel
    name: PersonName


_EVIDENCE_AT = "Mốc HH:MM:SS của đúng dòng transcript làm bằng chứng, không kèm ngoặc vuông"


class ReportItem(BaseModel):
    content: str = Field(description="Một ý duy nhất, tiếng Việt có dấu, ngắn gọn")
    evidence_at: str = Field(description=_EVIDENCE_AT)


class ActionItem(BaseModel):
    task: str = Field(description="Việc cần làm, bắt đầu bằng động từ")
    owner: str | None = Field(
        description="Tên người được giao, viết đúng như trong transcript (kể cả nhãn SPEAKER_xx); "
        "null nếu chưa ai nhận"
    )
    deadline: str | None = Field(description="Hạn hoàn thành giữ nguyên cách nói; null nếu không nêu")
    evidence_at: str = Field(description=_EVIDENCE_AT)


class MeetingReport(BaseModel):
    """Biên bản 4 phần. Cũng là khuôn structured outputs gửi cho LLM (mô tả trường đi kèm schema)."""

    goals: list[ReportItem] = Field(description="Mục tiêu cuộc họp, mỗi mục tiêu một phần tử")
    decisions: list[ReportItem] = Field(description="Quyết định cốt lõi đã được chốt rõ ràng")
    open_issues: list[ReportItem] = Field(
        description="Đề xuất, tranh luận hoặc câu hỏi chưa chốt; không lặp lại việc đã có trong action_items"
    )
    action_items: list[ActionItem] = Field(
        description="Mọi việc cần làm, kể cả việc chưa có người nhận (owner null)"
    )


class ReportEdit(BaseModel):
    """Bản biên bản người dùng gửi lên, kèm hai phiên bản họ đã đọc để không ghi đè bản mới hơn."""

    content: MeetingReport
    expected_revision: int | None = Field(description="revision của biên bản đã đọc; null nếu chưa có biên bản")
    transcript_revision: int = Field(description="revision của transcript mà người dùng đã đối chiếu")


class ReportDraft(BaseModel):
    """Biên bản sắp lưu, kèm phiên bản transcript mà nó được tạo từ đó."""

    meeting_id: str
    transcript_revision: int
    content: MeetingReport
    warnings: list[str]
    source: ReportSource
    llm_model: str | None
    prompt_version: str | None


class Report(ReportDraft):
    revision: int
    stale: bool = Field(description="true khi transcript đã đổi sau lúc tạo biên bản này")
    created_at: datetime
    updated_at: datetime
