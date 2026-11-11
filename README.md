# VoxScribe (Windows)

Ứng dụng Windows ghi âm cuộc họp, chép lời tiếng Việt, nhận diện người nói và tạo biên bản. Lộ trình ưu tiên bản Hybrid nhẹ cho laptop văn phòng. Bản ghi và hồ sơ giọng lưu trên máy, người dùng chọn khi nào gửi bản ghi để chép lời qua cloud.

## Cấu trúc & phân công

Xem [roadmap.md](roadmap.md) để biết công việc theo từng tệp, người phụ trách cấu hình và các mốc tích hợp.

| Thư mục | Phụ trách | Nội dung |
|---|---|---|
| `apps/desktop-ui/` | Người 1 | Giao diện Desktop (React + Tauri) |
| `services/backend/audio_engine/` | Người 1 | Thu âm Mic + Loopback, mix stereo, lọc nhiễu, VAD |
| `services/backend/speech_ai/` | Người 2 | Chép lời, phân tách người nói qua cloud, so khớp giọng bằng ONNX trên máy |
| `services/backend/core_app/` | Người 3 | FastAPI, SQLite + sqlite-vec, LLM agent, xuất báo cáo |
| `shared/schemas/` | TV1 (audio), TV2 (transcript) | JSON contract trao đổi giữa các module |
| `scripts/` | TV1 (bộ cài), TV2 (model) | Build .exe, tải model |

## Chạy thử

Lệnh phát triển hiện tại dùng bộ phụ thuộc thử nghiệm. Bộ phụ thuộc cho bản Hybrid sẽ được tách trong giai đoạn triển khai.

```bash
cd services/backend && pip install -r requirements.txt && python main.py
```

```bash
cd apps/desktop-ui && npm install && npm run dev
```
