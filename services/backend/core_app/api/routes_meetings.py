"""API lấy danh sách họp, sửa lời thoại, tìm kiếm"""
from fastapi import APIRouter

router = APIRouter(prefix="/meetings", tags=["meetings"])
