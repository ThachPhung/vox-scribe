"""API danh sách cuộc họp, transcript, nhãn người nói và biên bản."""
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from core_app.api.dependencies import Db, LlmReportGenerator, ReportSlots
from core_app.database import repositories
from core_app.database.models import (
    Meeting,
    MeetingSpeaker,
    Report,
    ReportDraft,
    ReportEdit,
    ReportSource,
    Transcript,
    TranscriptIn,
)
from core_app.exporters.docx_exporter import build_minutes_docx
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
        return repositories.save_generated_report(db, draft, expected_revision=_revision_of(previous))


@router.put("/{meeting_id}/report")
def save_edited_report(meeting_id: str, body: ReportEdit, db: Db) -> Report:
    """Lưu biên bản người dùng sửa hoặc tự viết, theo đúng hai phiên bản họ đã đọc (409 nếu đã có bản mới hơn).

    Biên bản giữ stale cho tới khi người dùng gửi transcript_revision mới nhất, tức đã đối chiếu lại.
    """
    transcript = repositories.get_transcript(db, meeting_id)
    previous = repositories.find_report(db, meeting_id)
    draft = ReportDraft(
        meeting_id=meeting_id,
        transcript_revision=body.transcript_revision,
        content=body.content,
        warnings=find_report_warnings(body.content, build_transcript_lines(transcript.segments)),
        source=previous.source if previous else ReportSource.MANUAL,
        llm_model=previous.llm_model if previous else None,
        prompt_version=previous.prompt_version if previous else None,
    )
    return repositories.save_edited_report(db, draft, expected_revision=body.expected_revision)


class ExportFormat(StrEnum):
    DOCX = "docx"


DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/{meeting_id}/report/export", response_class=Response)
def export_report(
    meeting_id: str, db: Db, export_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.DOCX
) -> Response:
    """Tải biên bản về máy; PDF và Markdown sẽ thêm vào ExportFormat ở bước sau."""
    content = build_minutes_docx(
        repositories.get_meeting(db, meeting_id),
        repositories.get_report(db, meeting_id),
        repositories.list_meeting_speakers(db, meeting_id),
    )
    filename = f"bien-ban-{meeting_id[:8]}.{export_format}"
    return Response(
        content,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _revision_of(report: Report | None) -> int | None:
    return report.revision if report is not None else None
