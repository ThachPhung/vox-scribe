"""API điều khiển Bắt đầu / Tạm dừng / Kết thúc thu"""
from fastapi import APIRouter

router = APIRouter(prefix="/recording", tags=["recording"])
