"""API thêm/sửa/xóa danh bạ giọng nói (Enrollment)"""
from fastapi import APIRouter

router = APIRouter(prefix="/speakers", tags=["speakers"])
