# VoxScribe (Windows)

Ứng dụng ghi âm cuộc họp, chuyển giọng nói thành văn bản, nhận diện người nói và tạo biên bản tự động — chạy hoàn toàn trên máy người dùng.

## Cấu trúc & phân công

Xem [roadmap.md](roadmap.md) để biết công việc theo từng tệp, người phụ trách cấu hình và các mốc tích hợp.

| Thư mục | Phụ trách | Nội dung |
|---|---|---|
| `apps/desktop-ui/` | Người 1 | Giao diện Desktop (React + Tauri) |
| `services/backend/audio_engine/` | Người 1 | Thu âm Mic + Loopback, mix stereo, lọc nhiễu, VAD |
| `services/backend/speech_ai/` | Người 2 | WhisperX, pyannote, voiceprint, so khớp người nói |
| `services/backend/core_app/` | Người 3 | FastAPI, SQLite + sqlite-vec, LLM agent, xuất báo cáo |
| `shared/schemas/` | TV1 (audio), TV2 (transcript) | JSON contract trao đổi giữa các module |
| `scripts/` | TV1 (bộ cài), TV2 (model) | Build .exe, tải model |

## Chạy thử

```bash
cd services/backend && pip install -r requirements.txt && python main.py
```

```bash
cd apps/desktop-ui && npm install && npm run dev
```
