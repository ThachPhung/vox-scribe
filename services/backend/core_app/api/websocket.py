"""Đẩy trạng thái thu âm, sóng âm, tiến độ xử lý AI và sự kiện Zoom/Teams lên giao diện."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from core_app.api.dependencies import ALLOWED_ORIGINS, get_event_hub
from core_app.database.models import JobKind, JobStatus

router = APIRouter()


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
        message = event.model_dump(mode="json")
        for websocket in list(self._connections):
            try:
                await websocket.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                self.disconnect(websocket)


EventHubDep = Annotated[EventHub, Depends(get_event_hub)]


@router.websocket("/ws")
async def events_ws(websocket: WebSocket, hub: EventHubDep) -> None:
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
