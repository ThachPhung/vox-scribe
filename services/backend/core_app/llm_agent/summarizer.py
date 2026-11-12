"""Agent tổng hợp báo cáo theo ngữ cảnh cuộc họp."""
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import openai
from openai import OpenAI
from openai.types.responses import ParsedResponse
from pydantic import ValidationError

from core_app.database.models import MeetingReport, Segment

PROMPT_VERSION = "report-vi-v2"
PROMPT_PATH = Path(__file__).parent / "prompts" / "report_vi.md"
MAX_INPUT_TOKENS = 922_000
LONG_CONTEXT_INPUT_TOKENS = 272_000
MERGE_GAP_SEC = 30.0

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptLine:
    timestamp: str
    speaker: str
    text: str


class EmptyTranscriptError(ValueError):
    pass


class ReportGenerationError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class GenerationInProgressError(Exception):
    pass


class GenerationCapacityError(Exception):
    """Quá tải tạm thời: đã đủ số biên bản được tạo cùng lúc."""


class ReportGenerationSlots:
    """Chặn tạo trùng biên bản cho cùng một cuộc họp và giới hạn số lần gọi LLM cùng lúc."""

    def __init__(self, max_concurrent: int) -> None:
        self._max_concurrent = max_concurrent
        self._active: set[str] = set()
        self._lock = threading.Lock()

    @contextmanager
    def reserve(self, meeting_id: str) -> Iterator[None]:
        with self._lock:
            if meeting_id in self._active:
                raise GenerationInProgressError("Cuộc họp này đang được tạo biên bản, hãy chờ kết quả")
            if len(self._active) >= self._max_concurrent:
                raise GenerationCapacityError("Đang tạo quá nhiều biên bản cùng lúc, hãy thử lại sau")
            self._active.add(meeting_id)
        try:
            yield
        finally:
            with self._lock:
                self._active.discard(meeting_id)


class ReportGenerator(Protocol):
    @property
    def model_name(self) -> str: ...

    def generate(self, transcript_text: str) -> MeetingReport: ...


def format_timestamp(seconds: float) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def build_transcript_lines(segments: list[Segment]) -> list[TranscriptLine]:
    """Gộp câu liền nhau của cùng một người (nghỉ không quá MERGE_GAP_SEC), giữ mốc giờ của câu đầu.

    Khoảng trắng và xuống dòng trong câu được gộp thành một dấu cách, để nội dung câu nói không giả
    được thành một dòng "[HH:MM:SS] Tên: ..." mới.
    """
    lines: list[TranscriptLine] = []
    last_end = 0.0
    for segment in segments:
        text = " ".join(segment.text.split())
        if not text:
            continue
        speaker = segment.speaker_name or segment.speaker_label
        continues_turn = bool(lines) and lines[-1].speaker == speaker and segment.start_sec - last_end <= MERGE_GAP_SEC
        if continues_turn:
            previous = lines[-1]
            lines[-1] = TranscriptLine(previous.timestamp, speaker, f"{previous.text} {text}")
        else:
            lines.append(TranscriptLine(format_timestamp(segment.start_sec), speaker, text))
        last_end = segment.end_sec
    return lines


def render_transcript(lines: list[TranscriptLine]) -> str:
    return "\n".join(f"[{line.timestamp}] {line.speaker}: {line.text}" for line in lines)


def summarize_meeting(lines: list[TranscriptLine], generator: ReportGenerator) -> MeetingReport:
    if not lines:
        raise EmptyTranscriptError("Cuộc họp chưa có transcript để tạo biên bản")
    return generator.generate(render_transcript(lines))


@dataclass(frozen=True)
class OpenAISettings:
    model: str
    reasoning_effort: ReasoningEffort


class OpenAIReportGenerator:
    """Chỗ duy nhất trong backend biết SDK openai."""

    def __init__(self, client: OpenAI, settings: OpenAISettings) -> None:
        self._client = client
        self._settings = settings
        self._instructions = PROMPT_PATH.read_text(encoding="utf-8")

    @property
    def model_name(self) -> str:
        return self._settings.model

    def generate(self, transcript_text: str) -> MeetingReport:
        started = time.perf_counter()
        try:
            self._check_input_size(transcript_text)
            response = self._client.responses.parse(
                model=self._settings.model,
                instructions=self._instructions,
                input=transcript_text,
                text_format=MeetingReport,
                reasoning={"effort": self._settings.reasoning_effort},
            )
        except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as error:
            raise ReportGenerationError(
                "Không kết nối được OpenAI hoặc dịch vụ đang quá tải, hãy thử lại sau", retryable=True
            ) from error
        except openai.APIStatusError as error:
            raise ReportGenerationError(
                f"OpenAI từ chối yêu cầu (mã {error.status_code})", retryable=False
            ) from error
        except ValidationError as error:
            raise ReportGenerationError(
                "Biên bản model trả về bị cắt giữa chừng hoặc sai khuôn, chưa được lưu", retryable=False
            ) from error
        logger.info(
            "Tạo biên bản bằng %s: %s token vào, %.1f giây",
            self._settings.model,
            response.usage.input_tokens if response.usage is not None else "không rõ",
            time.perf_counter() - started,
        )
        return _parsed_report(response)

    def _check_input_size(self, transcript_text: str) -> None:
        """Chỉ gọi API đếm token khi transcript có thể vượt ngưỡng giá; số token không vượt số byte UTF-8."""
        input_bytes = len(transcript_text.encode()) + len(self._instructions.encode())
        if input_bytes <= LONG_CONTEXT_INPUT_TOKENS:
            return
        input_tokens = self._client.responses.input_tokens.count(
            model=self._settings.model, instructions=self._instructions, input=transcript_text
        ).input_tokens
        if input_tokens > MAX_INPUT_TOKENS:
            raise ReportGenerationError(
                f"Transcript quá dài ({input_tokens} token, tối đa {MAX_INPUT_TOKENS})", retryable=False
            )
        if input_tokens > LONG_CONTEXT_INPUT_TOKENS:
            logger.warning("Transcript %d token vượt %d: OpenAI tính giá cao hơn", input_tokens, LONG_CONTEXT_INPUT_TOKENS)


def _parsed_report(response: ParsedResponse[MeetingReport]) -> MeetingReport:
    if response.status == "incomplete":
        raise ReportGenerationError("Biên bản bị cắt giữa chừng, chưa được lưu", retryable=False)
    if _has_refusal(response):
        raise ReportGenerationError("Model từ chối tạo biên bản cho transcript này", retryable=False)
    if response.output_parsed is None:
        raise ReportGenerationError("Không đọc được biên bản model trả về", retryable=False)
    return response.output_parsed


def _has_refusal(response: ParsedResponse[MeetingReport]) -> bool:
    return any(
        content.type == "refusal"
        for output in response.output
        if output.type == "message"
        for content in output.content
    )
