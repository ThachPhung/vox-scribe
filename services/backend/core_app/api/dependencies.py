"""Phụ thuộc dùng chung cho các route: kết nối DB, bộ tạo biên bản, bộ phát sự kiện."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, status
from starlette.requests import HTTPConnection

from core_app.database.connection import open_connection
from core_app.llm_agent.summarizer import ReportGenerationSlots, ReportGenerator

if TYPE_CHECKING:
    from core_app.api.websocket import EventHub
    from core_app.recording.session import RecordingSessions

ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://tauri.localhost",
    "tauri://localhost",
)


@dataclass(frozen=True)
class Services:
    db_path: Path
    report_generator: ReportGenerator | None
    report_slots: ReportGenerationSlots
    event_hub: EventHub
    recordings: RecordingSessions
    start_watcher: bool = True


def get_services(connection: HTTPConnection) -> Services:
    return connection.app.state.services


def get_db(services: Annotated[Services, Depends(get_services)]) -> Iterator[sqlite3.Connection]:
    with closing(open_connection(services.db_path)) as connection:
        yield connection


def get_report_generator(services: Annotated[Services, Depends(get_services)]) -> ReportGenerator:
    if services.report_generator is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Tạo biên bản bằng AI đang tắt hoặc chưa cấu hình OPENAI_API_KEY",
        )
    return services.report_generator


def get_report_slots(services: Annotated[Services, Depends(get_services)]) -> ReportGenerationSlots:
    return services.report_slots


def get_event_hub(services: Annotated[Services, Depends(get_services)]) -> EventHub:
    return services.event_hub


def get_recordings(services: Annotated[Services, Depends(get_services)]) -> RecordingSessions:
    return services.recordings


Db = Annotated[sqlite3.Connection, Depends(get_db)]
LlmReportGenerator = Annotated[ReportGenerator, Depends(get_report_generator)]
ReportSlots = Annotated[ReportGenerationSlots, Depends(get_report_slots)]
