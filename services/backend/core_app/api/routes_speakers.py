"""API danh bạ giọng nói và xác nhận tên cho nhãn người nói trong một cuộc họp."""
from fastapi import APIRouter, status
from pydantic import BaseModel

from core_app.api.dependencies import Db
from core_app.database import repositories
from core_app.database.models import PersonName, Speaker, SpeakerConfirmation

router = APIRouter(prefix="/speakers", tags=["speakers"])


class RenameSpeakerRequest(BaseModel):
    name: PersonName


class ConfirmSpeakerResponse(BaseModel):
    changed: bool


@router.get("")
def list_speakers(db: Db) -> list[Speaker]:
    return repositories.list_speakers(db)


@router.patch("/{speaker_id}")
def rename_speaker(speaker_id: int, body: RenameSpeakerRequest, db: Db) -> Speaker:
    return repositories.rename_speaker(db, speaker_id, body.name)


@router.delete("/{speaker_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_speaker(speaker_id: int, db: Db) -> None:
    repositories.delete_speaker(db, speaker_id)


@router.post("/confirm")
def confirm_speaker(body: SpeakerConfirmation, db: Db) -> ConfirmSpeakerResponse:
    """Gửi lại đúng xác nhận cũ trả về changed=false và không cập nhật vector lần hai."""
    return ConfirmSpeakerResponse(changed=repositories.confirm_speaker(db, body))
