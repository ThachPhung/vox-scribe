"""Xuất biên bản cuộc họp ra Word (.docx) theo thể thức văn bản hành chính (Nghị định 30/2020/NĐ-CP)."""
import re
from io import BytesIO

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from core_app.database.models import ActionItem, Meeting, MeetingSpeaker, Report, ReportItem

FONT_NAME = "Times New Roman"
BODY_SIZE = Pt(13)
TITLE_SIZE = Pt(14)
MISSING = "Chưa rõ"
NONE_RECORDED = "Không có."
HEADER_SHADE = "D9D9D9"
XML_INVALID_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
ACTION_COLUMNS = (
    ("STT", Cm(1.2)),
    ("Nội dung công việc", Cm(6.8)),
    ("Người phụ trách", Cm(3.5)),
    ("Thời hạn", Cm(3.0)),
    ("Mốc", Cm(2.0)),
)


def build_minutes_docx(meeting: Meeting, report: Report, speakers: list[MeetingSpeaker]) -> bytes:
    """Nhãn SPEAKER_xx ở cột người phụ trách được thay bằng tên đã xác nhận nếu có."""
    names = {speaker.speaker_label: speaker.speaker_name for speaker in speakers if speaker.speaker_name}
    document = Document()
    _set_page_and_font(document)
    _add_national_header(document)
    _add_title(document, meeting.title)
    _add_general_info(document, meeting, speakers)
    _add_items_section(document, "II. MỤC TIÊU CUỘC HỌP", report.content.goals)
    _add_items_section(document, "III. QUYẾT ĐỊNH CỐT LÕI", report.content.decisions)
    _add_items_section(document, "IV. VẤN ĐỀ CÒN BỎ NGỎ", report.content.open_issues)
    _add_heading(document, "V. BẢNG PHÂN CÔNG CÔNG VIỆC")
    _add_action_table(document, report.content.action_items, names)
    _add_review_notes(document, report)
    _add_signatures(document)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _set_page_and_font(document: DocxDocument) -> None:
    for section in document.sections:
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.top_margin = section.bottom_margin = Cm(2)
        section.left_margin, section.right_margin = Cm(3), Cm(1.5)
    normal = document.styles["Normal"]
    normal.font.name = FONT_NAME
    normal.font.size = BODY_SIZE
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT_NAME)
    normal.paragraph_format.space_after = Pt(3)


def _add_national_header(document: DocxDocument) -> None:
    _add_centered(document, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", Pt(12)).bold = True
    motto = _add_centered(document, "Độc lập - Tự do - Hạnh phúc")
    motto.bold = motto.underline = True


def _add_title(document: DocxDocument, meeting_title: str) -> None:
    document.add_paragraph()
    _add_centered(document, "BIÊN BẢN CUỘC HỌP", TITLE_SIZE).bold = True
    _add_centered(document, meeting_title).bold = True


def _add_general_info(document: DocxDocument, meeting: Meeting, speakers: list[MeetingSpeaker]) -> None:
    _add_heading(document, "I. THÔNG TIN CHUNG")
    started = meeting.started_at.astimezone()
    _add_run(document.add_paragraph(), f"Thời gian bắt đầu: {started:%H} giờ {started:%M}, ngày {started:%d/%m/%Y}.")
    if meeting.duration_sec is not None:
        _add_run(document.add_paragraph(), f"Thời lượng: {_describe_duration(meeting.duration_sec)}.")
    attendees = [speaker.speaker_name or f"Người nói chưa xác định ({speaker.speaker_label})" for speaker in speakers]
    _add_run(document.add_paragraph(), f"Thành phần tham dự: {', '.join(attendees) if attendees else MISSING}.")


def _describe_duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"khoảng {minutes} phút" if minutes >= 1 else "dưới 1 phút"


def _add_items_section(document: DocxDocument, heading: str, items: list[ReportItem]) -> None:
    _add_heading(document, heading)
    if not items:
        _add_run(document.add_paragraph(), NONE_RECORDED).italic = True
    for number, item in enumerate(items, start=1):
        paragraph = document.add_paragraph()
        _add_run(paragraph, f"{number}. {item.content} ")
        _add_run(paragraph, f"(mốc {item.evidence_at})").italic = True


def _add_action_table(document: DocxDocument, items: list[ActionItem], names: dict[str, str]) -> None:
    table = document.add_table(rows=1, cols=len(ACTION_COLUMNS))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, (title, _width) in zip(table.rows[0].cells, ACTION_COLUMNS):
        _write_centered_cell(cell, title).bold = True
        _shade(cell, HEADER_SHADE)
    _repeat_as_header(table)
    for number, item in enumerate(items, start=1):
        owner = names.get(item.owner, item.owner) if item.owner else MISSING
        values = (str(number), item.task, owner, item.deadline or MISSING, item.evidence_at)
        for cell, value in zip(table.add_row().cells, values):
            _write_cell(cell, value)
    _set_column_widths(table)
    if not items:
        _add_run(document.add_paragraph(), NONE_RECORDED).italic = True


def _add_review_notes(document: DocxDocument, report: Report) -> None:
    notes = list(report.warnings)
    if report.stale:
        notes.insert(0, "Transcript đã thay đổi sau khi tạo biên bản này, cần tạo lại hoặc rà soát.")
    if not notes:
        return
    _add_heading(document, "VI. LƯU Ý KHI RÀ SOÁT (xóa mục này trước khi ban hành)")
    for note in notes:
        _add_run(document.add_paragraph(), f"- {note}").italic = True


def _add_signatures(document: DocxDocument) -> None:
    document.add_paragraph()
    table = document.add_table(rows=2, cols=2)
    for cell, role in zip(table.rows[0].cells, ("THƯ KÝ", "CHỦ TRÌ")):
        _write_centered_cell(cell, role).bold = True
    for cell in table.rows[1].cells:
        _write_centered_cell(cell, "(Ký, ghi rõ họ tên)").italic = True


def _add_heading(document: DocxDocument, text: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(6)
    _add_run(paragraph, text).bold = True


def _add_centered(document: DocxDocument, text: str, size: Pt = BODY_SIZE) -> Run:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_after = Pt(0)
    run = _add_run(paragraph, text)
    run.font.size = size
    return run


def _write_cell(cell: _Cell, text: str) -> Run:
    return _add_run(cell.paragraphs[0], text)


def _write_centered_cell(cell: _Cell, text: str) -> Run:
    cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    return _write_cell(cell, text)


def _add_run(paragraph: Paragraph, text: str) -> Run:
    """Mọi chữ đi vào file đều qua đây: bỏ ký tự điều khiển mà XML của Word không chấp nhận."""
    return paragraph.add_run(XML_INVALID_CHARS.sub("", text))


def _shade(cell: _Cell, fill: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def _repeat_as_header(table: Table) -> None:
    """Dòng tiêu đề bảng được lặp lại ở đầu mỗi trang khi bảng dài."""
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    table.rows[0]._tr.get_or_add_trPr().append(header)


def _set_column_widths(table: Table) -> None:
    for row in table.rows:
        for cell, (_title, width) in zip(row.cells, ACTION_COLUMNS):
            cell.width = width
