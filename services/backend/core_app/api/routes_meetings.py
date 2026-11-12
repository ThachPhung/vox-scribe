"""API danh sách cuộc họp, transcript, nhãn người nói và biên bản."""
from fastapi import APIRouter, HTTPException, status

from core_app.api.dependencies import Db, LlmReportGenerator, ReportSlots
from core_app.database import repositories
from core_app.database.models import (
    Meeting,
    MeetingReport,
    MeetingSpeaker,
    Report,
    ReportDraft,
    ReportSource,
    Transcript,
    TranscriptIn,
)
from core_app.llm_agent.action_extractor import find_report_warnings
from core_app.llm_agent.summarizer import PROMPT_VERSION, build_transcript_lines, summarize_meeting

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.get("")
def list_meetings(db: Db) -> list[Meeting]:
    return repositories.list_meetings(db)


@router.get("/{meeting_id}")
def get_meeting(meeting_id: str, db: Db) -> Meeting:
    return repositories.get_meeting(db, meeting_id)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: str, db: Db) -> None:
    repositories.delete_meeting(db, meeting_id)


@router.put("/{meeting_id}/transcript")
def save_transcript(meeting_id: str, body: TranscriptIn, db: Db) -> Transcript:
    """Nạp transcript theo transcript_contract.json; gửi lại sẽ thay thế, không tạo bản trùng."""
    if body.meeting_id != meeting_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"meeting_id trong transcript ({body.meeting_id}) khác với đường dẫn ({meeting_id})",
        )
    return repositories.save_transcript(db, body)


@router.get("/{meeting_id}/transcript")
def get_transcript(meeting_id: str, db: Db) -> Transcript:
    return repositories.get_transcript(db, meeting_id)


@router.get("/{meeting_id}/speakers")
def list_meeting_speakers(meeting_id: str, db: Db) -> list[MeetingSpeaker]:
    return repositories.list_meeting_speakers(db, meeting_id)


@router.get("/{meeting_id}/report")
def get_report(meeting_id: str, db: Db) -> Report:
    return repositories.get_report(db, meeting_id)


@router.post("/{meeting_id}/report/generate")
def generate_report(
    meeting_id: str, db: Db, generator: LlmReportGenerator, slots: ReportSlots
) -> Report:
    """Gọi route này nghĩa là người dùng đã đồng ý gửi transcript lên LLM cloud.

    Nếu transcript hoặc biên bản bị đổi trong lúc chờ LLM, kết quả không được lưu (409).
    """
    with slots.reserve(meeting_id):
        transcript = repositories.get_transcript(db, meeting_id)
        previous = repositories.find_report(db, meeting_id)
        lines = build_transcript_lines(transcript.segments)
        content = summarize_meeting(lines, generator)
        draft = ReportDraft(
            meeting_id=meeting_id,
            transcript_revision=transcript.revision,
            content=content,
            warnings=find_report_warnings(content, lines),
            source=ReportSource.LLM,
            llm_model=generator.model_name,
            prompt_version=PROMPT_VERSION,
        )
        return repositories.save_report(db, draft, expected_revision=_revision_of(previous))


@router.put("/{meeting_id}/report")
def save_edited_report(meeting_id: str, body: MeetingReport, db: Db) -> Report:
    """Lưu biên bản người dùng sửa hoặc tự viết; giữ nguồn gốc của bản trước nếu có."""
    transcript = repositories.get_transcript(db, meeting_id)
    previous = repositories.find_report(db, meeting_id)
    draft = ReportDraft(
        meeting_id=meeting_id,
        transcript_revision=transcript.revision,
        content=body,
        warnings=find_report_warnings(body, build_transcript_lines(transcript.segments)),
        source=previous.source if previous else ReportSource.MANUAL,
        llm_model=previous.llm_model if previous else None,
        prompt_version=previous.prompt_version if previous else None,
    )
    return repositories.save_report(db, draft, expected_revision=_revision_of(previous))


def _revision_of(report: Report | None) -> int | None:
    return report.revision if report is not None else None
