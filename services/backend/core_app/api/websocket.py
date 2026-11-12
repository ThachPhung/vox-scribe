"""Đẩy trạng thái thu âm, sóng âm, tiến độ xử lý AI và sự kiện Zoom/Teams lên giao diện."""
import asyncio
from contextlib import suppress
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from core_app.api.dependencies import ALLOWED_ORIGINS, get_event_hub
from core_app.database.models import JobKind, JobStatus

router = APIRouter()

SEND_TIMEOUT_SEC = 2.0
SEND_ERRORS = (WebSocketDisconnect, RuntimeError, OSError, TimeoutError)


class RecordingStatusData(BaseModel):
    state: Literal["recording", "paused", "stopped"]
    elapsed_sec: float


class WaveformData(BaseModel):
    left: float = Field(ge=0, le=1)
    right: float = Field(ge=0, le=1)


class JobProgressData(BaseModel):
    job_id: int
    kind: JobKind
    status: JobStatus
    stage: str | None
    progress: float = Field(ge=0, le=1)


class JobErrorData(BaseModel):
    job_id: int
    message: str
    retryable: bool


class NetworkStatusData(BaseModel):
    online: bool


class AppDetectedData(BaseModel):
    app: Literal["zoom", "teams"]


class RecordingStatusEvent(BaseModel):
    type: Literal["recording.status"] = "recording.status"
    meeting_id: str
    data: RecordingStatusData


class WaveformEvent(BaseModel):
    type: Literal["recording.waveform"] = "recording.waveform"
    meeting_id: str
    data: WaveformData


class JobProgressEvent(BaseModel):
    type: Literal["job.progress"] = "job.progress"
    meeting_id: str
    data: JobProgressData


class JobErrorEvent(BaseModel):
    type: Literal["job.error"] = "job.error"
    meeting_id: str
    data: JobErrorData


class NetworkStatusEvent(BaseModel):
    type: Literal["network.status"] = "network.status"
    meeting_id: None = None
    data: NetworkStatusData


class AppDetectedEvent(BaseModel):
    type: Literal["app.detected"] = "app.detected"
    meeting_id: None = None
    data: AppDetectedData


WsEvent = Annotated[
    RecordingStatusEvent
    | WaveformEvent
    | JobProgressEvent
    | JobErrorEvent
    | NetworkStatusEvent
    | AppDetectedEvent,
    Field(discriminator="type"),
]


class EventHub:
    """Giữ các kết nối WebSocket đang mở và gửi cùng một sự kiện cho tất cả."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, event: WsEvent) -> None:
        """Gửi song song cho mọi UI; client lỗi, đã đóng hoặc chậm quá SEND_TIMEOUT_SEC bị ngắt kết nối."""
        message = event.model_dump(mode="json")
        await asyncio.gather(*(self._send(websocket, message) for websocket in list(self._connections)))

    async def _send(self, websocket: WebSocket, message: dict) -> None:
        try:
            await asyncio.wait_for(websocket.send_json(message), timeout=SEND_TIMEOUT_SEC)
        except SEND_ERRORS:
            await self._drop(websocket)

    async def _drop(self, websocket: WebSocket) -> None:
        """Đóng hẳn kết nối để UI biết mà nối lại, thay vì giữ một socket mở nhưng không còn nhận sự kiện."""
        self.disconnect(websocket)
        with suppress(*SEND_ERRORS):
            await asyncio.wait_for(
                websocket.close(code=status.WS_1011_INTERNAL_ERROR), timeout=SEND_TIMEOUT_SEC
            )


EventHubDep = Annotated[EventHub, Depends(get_event_hub)]


@router.websocket("/ws")
async def events_ws(websocket: WebSocket, hub: EventHubDep) -> None:
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await hub.connect(websocket)
    try:
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass
    finally:
        hub.disconnect(websocket)
