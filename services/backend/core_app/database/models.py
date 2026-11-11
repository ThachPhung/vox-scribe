"""Bảng SQLite và kiểu dữ liệu dùng chung: Meetings, Segments, Speakers, Jobs, Reports."""
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, FiniteFloat, model_validator

EMBEDDING_DIM = 192

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

MIGRATIONS: dict[int, str] = {1: _SCHEMA_V1, 2: _SCHEMA_V2}
SCHEMA_VERSION = max(MIGRATIONS)


def normalize_person_name(name: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFC", name).split())
    if not normalized:
        raise ValueError("Tên không được để trống")
    return normalized


PersonName = Annotated[str, AfterValidator(normalize_person_name)]


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
    speaker_label: str = Field(min_length=1)
    speaker_name: str | None = None
    text: str
    words: list[Word] | None = None

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "TranscriptSegmentIn":
        _require_ordered(self.start, self.end)
        return self


class TranscriptIn(BaseModel):
    """Transcript do speech_ai (TV2) trả về."""

    meeting_id: str
    language: str | None = None
    segments: list[TranscriptSegmentIn]


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


class Speaker(BaseModel):
    id: int
    name: str
    created_at: datetime
    updated_at: datetime


class MeetingSpeaker(BaseModel):
    speaker_label: str
    speaker_id: int | None
    speaker_name: str | None
    match_score: float | None
    confirmed_at: datetime | None


class VoiceEmbedding(BaseModel):
    values: list[FiniteFloat] = Field(min_length=EMBEDDING_DIM, max_length=EMBEDDING_DIM)
    model_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _not_all_zero(self) -> "VoiceEmbedding":
        if not any(self.values):
            raise ValueError("Vector giọng toàn số 0, không so khớp được")
        return self


class SpeakerMatch(BaseModel):
    speaker_id: int
    name: str
    similarity: float


class SpeakerConfirmation(BaseModel):
    meeting_id: str
    speaker_label: str
    name: PersonName
    embedding: VoiceEmbedding | None = None


class ReportItem(BaseModel):
    content: str
    evidence_at: str


class ActionItem(BaseModel):
    task: str
    owner: str | None
    deadline: str | None
    evidence_at: str


class MeetingReport(BaseModel):
    """Biên bản 4 phần. Cũng là khuôn structured outputs gửi cho LLM."""

    goals: list[ReportItem]
    decisions: list[ReportItem]
    open_issues: list[ReportItem]
    action_items: list[ActionItem]


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
