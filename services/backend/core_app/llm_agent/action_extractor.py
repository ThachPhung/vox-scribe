"""Agent bóc tách đầu việc, người phụ trách và hạn chót."""
import unicodedata
from collections.abc import Iterator

from core_app.database.models import ActionItem, MeetingReport
from core_app.llm_agent.summarizer import TranscriptLine


def find_report_warnings(report: MeetingReport, lines: list[TranscriptLine]) -> list[str]:
    """Đánh dấu chỗ thiếu thông tin; khi có transcript thì đối chiếu thêm để bắt nội dung bịa."""
    warnings = [warning for item in report.action_items for warning in _missing_field_warnings(item)]
    if lines:
        warnings += _unsupported_by_transcript(report, lines)
    return warnings


def _missing_field_warnings(item: ActionItem) -> list[str]:
    warnings: list[str] = []
    if item.owner is None:
        warnings.append(f'Đầu việc "{item.task}" chưa rõ người phụ trách')
    if item.deadline is None:
        warnings.append(f'Đầu việc "{item.task}" chưa rõ hạn hoàn thành')
    return warnings


def _unsupported_by_transcript(report: MeetingReport, lines: list[TranscriptLine]) -> list[str]:
    transcript_text = _comparable(" ".join(f"{line.speaker} {line.text}" for line in lines))
    timestamps = {line.timestamp for line in lines}
    warnings = [
        f'Người phụ trách "{item.owner}" của đầu việc "{item.task}" không có trong transcript'
        for item in report.action_items
        if item.owner is not None and _comparable(item.owner) not in transcript_text
    ]
    for title, evidence_at in _evidence_of(report):
        if evidence_at.strip("[] ") not in timestamps:
            warnings.append(f'Mốc {evidence_at} của mục "{title}" không khớp dòng nào trong transcript')
    return warnings


def _evidence_of(report: MeetingReport) -> Iterator[tuple[str, str]]:
    for item in [*report.goals, *report.decisions, *report.open_issues]:
        yield item.content, item.evidence_at
    for action in report.action_items:
        yield action.task, action.evidence_at


def _comparable(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()
