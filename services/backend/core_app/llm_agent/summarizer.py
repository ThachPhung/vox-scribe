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

from core_app.database.models import MeetingReport, Segment

PROMPT_VERSION = "report-vi-v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / "report_vi.md"
MAX_INPUT_TOKENS = 922_000
LONG_CONTEXT_INPUT_TOKENS = 272_000

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
                raise GenerationInProgressError("Đang tạo quá nhiều biên bản cùng lúc, hãy thử lại sau")
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
    """Gộp các câu liền nhau của cùng một người, giữ mốc giờ của câu đầu."""
    lines: list[TranscriptLine] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        speaker = segment.speaker_name or segment.speaker_label
        if lines and lines[-1].speaker == speaker:
            previous = lines[-1]
            lines[-1] = TranscriptLine(previous.timestamp, speaker, f"{previous.text} {text}")
        else:
            lines.append(TranscriptLine(format_timestamp(segment.start_sec), speaker, text))
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
            input_tokens = self._count_input_tokens(transcript_text)
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
        logger.info(
            "Tạo biên bản bằng %s: %d token vào, %.1f giây",
            self._settings.model,
            input_tokens,
            time.perf_counter() - started,
        )
        return _parsed_report(response)

    def _count_input_tokens(self, transcript_text: str) -> int:
        input_tokens = self._client.responses.input_tokens.count(
            model=self._settings.model, instructions=self._instructions, input=transcript_text
        ).input_tokens
        if input_tokens > MAX_INPUT_TOKENS:
            raise ReportGenerationError(
                f"Transcript quá dài ({input_tokens} token, tối đa {MAX_INPUT_TOKENS})", retryable=False
            )
        if input_tokens > LONG_CONTEXT_INPUT_TOKENS:
            logger.warning("Transcript %d token vượt %d: OpenAI tính giá cao hơn", input_tokens, LONG_CONTEXT_INPUT_TOKENS)
        return input_tokens


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
