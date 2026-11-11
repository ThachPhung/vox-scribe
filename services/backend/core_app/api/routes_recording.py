"""API điều khiển Bắt đầu / Kết thúc thu. Giai đoạn B sẽ nối thêm audio_engine và tác vụ chép lời."""
from fastapi import APIRouter, BackgroundTasks, status
from pydantic import BaseModel, Field

from core_app.api.dependencies import Db
from core_app.api.websocket import EventHubDep, RecordingStatusData, RecordingStatusEvent
from core_app.database import repositories
from core_app.database.models import CaptureMode, Meeting

router = APIRouter(prefix="/recording", tags=["recording"])


class StartRecordingRequest(BaseModel):
    title: str = Field(min_length=1)
    capture_mode: CaptureMode


@router.post("/start", status_code=status.HTTP_201_CREATED)
def start_recording(
    body: StartRecordingRequest, db: Db, hub: EventHubDep, background: BackgroundTasks
) -> Meeting:
    meeting = repositories.create_meeting(db, body.title, body.capture_mode)
    status_data = RecordingStatusData(state="recording", elapsed_sec=0)
    background.add_task(hub.broadcast, RecordingStatusEvent(meeting_id=meeting.id, data=status_data))
    return meeting


@router.post("/{meeting_id}/stop")
def stop_recording(meeting_id: str, db: Db, hub: EventHubDep, background: BackgroundTasks) -> Meeting:
    meeting = repositories.finish_recording(db, meeting_id)
    status_data = RecordingStatusData(state="stopped", elapsed_sec=meeting.duration_sec or 0)
    background.add_task(hub.broadcast, RecordingStatusEvent(meeting_id=meeting.id, data=status_data))
    return meeting
