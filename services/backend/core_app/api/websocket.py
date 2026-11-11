"""Đẩy tiến độ xử lý AI (0-100%) lên giao diện."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def progress_ws(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
