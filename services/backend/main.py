"""Điểm khởi chạy FastAPI Server."""
import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import get_args

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import OpenAI

from audio_engine.process_watcher import AppEvent, ProcessWatcher
from core_app.api import routes_meetings, routes_recording, routes_speakers, websocket
from core_app.api.dependencies import ALLOWED_ORIGINS, Services
from core_app.api.websocket import AppDetectedData, AppDetectedEvent, EventHub, WsEvent
from core_app.database.connection import initialize_database, open_connection
from core_app.database.repositories import ConflictError, NotFoundError, close_unfinished_recordings
from core_app.llm_agent.summarizer import (
    EmptyTranscriptError,
    GenerationInProgressError,
    OpenAIReportGenerator,
    OpenAISettings,
    ReasoningEffort,
    ReportGenerationError,
    ReportGenerationSlots,
    ReportGenerator,
)
from core_app.recording.session import RecordingSessions

HOST = "127.0.0.1"
PORT = 8000
ENV_FILE = Path(__file__).parent / ".env"
DB_FILENAME = "voxscribe.db"
RECORDINGS_DIRNAME = "recordings"
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_LLM_MODEL = "gpt-6-luna"
DEFAULT_REASONING_EFFORT = "medium"
LLM_TIMEOUT_SEC = 120
LLM_MAX_RETRIES = 1
MAX_CONCURRENT_REPORTS = 2

logger = logging.getLogger("voxscribe")


def services_from_env() -> Services:
    """Đọc cấu hình từ biến môi trường (hoặc file .env) một lần khi server khởi động."""
    data_dir = _data_dir_from_env()
    return Services(
        db_path=data_dir / DB_FILENAME,
        report_generator=_report_generator_from_env(),
        report_slots=ReportGenerationSlots(MAX_CONCURRENT_REPORTS),
        event_hub=EventHub(),
        recordings=RecordingSessions(data_dir / RECORDINGS_DIRNAME, publish=lambda _event: None),
    )


def _data_dir_from_env() -> Path:
    configured = os.environ.get("VOXSCRIBE_DATA_DIR")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "VoxScribe"
    return Path.home() / ".voxscribe"


def _report_generator_from_env() -> ReportGenerator | None:
    provider = os.environ.get("LLM_PROVIDER", DEFAULT_LLM_PROVIDER)
    if provider == "none":
        logger.info("LLM_PROVIDER=none: tắt tạo biên bản bằng AI")
        return None
    if provider != "openai":
        raise ValueError(f"LLM_PROVIDER không hợp lệ: {provider} (chỉ nhận openai hoặc none)")
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("Chưa có OPENAI_API_KEY: tạo biên bản bằng AI sẽ trả lỗi 503")
        return None
    settings = OpenAISettings(
        model=os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL),
        reasoning_effort=_reasoning_effort_from_env(),
    )
    return OpenAIReportGenerator(OpenAI(timeout=LLM_TIMEOUT_SEC, max_retries=LLM_MAX_RETRIES), settings)


def _reasoning_effort_from_env() -> ReasoningEffort:
    effort = os.environ.get("LLM_REASONING_EFFORT", DEFAULT_REASONING_EFFORT)
    allowed = get_args(ReasoningEffort)
    if effort not in allowed:
        raise ValueError(f"LLM_REASONING_EFFORT không hợp lệ: {effort} (chỉ nhận {', '.join(allowed)})")
    return effort


def create_app(build_services: Callable[[], Services] = services_from_env) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = build_services()
        initialize_database(services.db_path)
        _close_unfinished_recordings(services.db_path)
        app.state.services = services
        publish = _thread_publisher(services.event_hub, asyncio.get_running_loop())
        services.recordings.set_publisher(publish)
        watcher = _start_meeting_watcher(publish) if services.start_watcher else None
        try:
            yield
        finally:
            if watcher is not None:
                watcher.stop()
            services.recordings.stop_all()

    app = FastAPI(title="VoxScribe Backend", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=list(ALLOWED_ORIGINS), allow_methods=["*"], allow_headers=["*"]
    )
    for module in (routes_recording, routes_meetings, routes_speakers, websocket):
        app.include_router(module.router)
    app.add_exception_handler(NotFoundError, _error_handler(status.HTTP_404_NOT_FOUND))
    app.add_exception_handler(ConflictError, _error_handler(status.HTTP_409_CONFLICT))
    app.add_exception_handler(EmptyTranscriptError, _error_handler(status.HTTP_409_CONFLICT))
    app.add_exception_handler(GenerationInProgressError, _error_handler(status.HTTP_409_CONFLICT))
    app.add_exception_handler(ReportGenerationError, _report_generation_error)
    app.add_exception_handler(RequestValidationError, _validation_error)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _close_unfinished_recordings(db_path: Path) -> None:
    with closing(open_connection(db_path)) as connection:
        closed = close_unfinished_recordings(connection)
    if closed:
        logger.warning("Đã đóng %d cuộc họp bị bỏ dở khi server tắt giữa lúc ghi", closed)


def _thread_publisher(hub: EventHub, loop: asyncio.AbstractEventLoop) -> Callable[[WsEvent], None]:
    """Cho thread nền (ghi âm, watcher) gửi sự kiện WebSocket qua event loop của server."""

    def publish(event: WsEvent) -> None:
        asyncio.run_coroutine_threadsafe(hub.broadcast(event), loop)

    return publish


def _start_meeting_watcher(publish: Callable[[WsEvent], None]) -> ProcessWatcher:
    def on_event(event: AppEvent) -> None:
        if event.running:
            logger.info("Phát hiện %s đang mở", event.app)
            publish(AppDetectedEvent(data=AppDetectedData(app=event.app)))

    watcher = ProcessWatcher()
    watcher.start(on_event)
    return watcher


def _error_handler(status_code: int) -> Callable[[Request, Exception], JSONResponse]:
    def handle(_request: Request, error: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=status_code)

    return handle


def _report_generation_error(_request: Request, error: ReportGenerationError) -> JSONResponse:
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE if error.retryable else status.HTTP_502_BAD_GATEWAY
    return JSONResponse({"detail": str(error), "retryable": error.retryable}, status_code=status_code)


def _validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
    """Không trả lại dữ liệu đầu vào: nó có thể chứa NaN/Infinity (không ghi được ra JSON) hoặc rất lớn."""
    errors = [{key: value for key, value in item.items() if key != "input"} for item in error.errors()]
    return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=HOST, port=PORT, env_file=ENV_FILE if ENV_FILE.exists() else None)
