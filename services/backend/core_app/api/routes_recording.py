"""API điều khiển Bắt đầu / Kết thúc thu: tạo cuộc họp và ghi WAV stereo qua audio_engine."""
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core_app.api.dependencies import Db, get_recordings
from core_app.api.websocket import EventHubDep, RecordingStatusData, RecordingStatusEvent
from core_app.database import repositories
from core_app.database.models import CaptureMode, Meeting
from core_app.recording.session import RecordingSessions

router = APIRouter(prefix="/recording", tags=["recording"])
logger = logging.getLogger("voxscribe.recording")

Recordings = Annotated[RecordingSessions, Depends(get_recordings)]


class StartRecordingRequest(BaseModel):
    title: str = Field(min_length=1)
    capture_mode: CaptureMode


@router.post("/start", status_code=status.HTTP_201_CREATED)
def start_recording(
    body: StartRecordingRequest, db: Db, hub: EventHubDep, recordings: Recordings, background: BackgroundTasks
) -> Meeting:
    meeting = repositories.create_meeting(db, body.title, body.capture_mode)
    try:
        recordings.start(meeting.id)
    except Exception as error:
        logger.exception("Không bắt đầu được ghi âm cho %s", meeting.id)
        repositories.finish_recording(db, meeting.id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Không mở được mic/loa để ghi âm: {error}"
        ) from error
    status_data = RecordingStatusData(state="recording", elapsed_sec=0)
    background.add_task(hub.broadcast, RecordingStatusEvent(meeting_id=meeting.id, data=status_data))
    return meeting


@router.post("/{meeting_id}/stop")
def stop_recording(
    meeting_id: str, db: Db, hub: EventHubDep, recordings: Recordings, background: BackgroundTasks
) -> Meeting:
    audio = recordings.stop(meeting_id) if recordings.is_recording(meeting_id) else None
    meeting = repositories.finish_recording(db, meeting_id)
    if audio is not None:
        meeting = repositories.attach_audio(db, meeting_id, *audio)
    status_data = RecordingStatusData(state="stopped", elapsed_sec=meeting.duration_sec or 0)
    background.add_task(hub.broadcast, RecordingStatusEvent(meeting_id=meeting.id, data=status_data))
    return meeting
