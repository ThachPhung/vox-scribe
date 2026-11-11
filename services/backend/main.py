"""Điểm khởi chạy FastAPI Server."""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core_app.api import routes_meetings, routes_recording, routes_speakers, websocket

app = FastAPI(title="VoxScribe Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

for r in (routes_recording, routes_meetings, routes_speakers, websocket):
    app.include_router(r.router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
