# Merge Notes — TV3 (Backend, Database & LLM Agent)

Ghi chú cho người review hoặc merge PR phần TV3. Đây không phải tài liệu theo dõi tiến độ.

## Phạm vi thay đổi
- Chỉ sửa trong: `services/backend/core_app/`, `services/backend/main.py`, `services/backend/requirements.txt`.
- File mới:
  - `core_app/api/dependencies.py`
  - `core_app/llm_agent/prompts/report_vi.md`
  - `services/backend/requirements-offline.txt`
  - `services/backend/.env.example`
- Không sửa thư mục của TV1, TV2, `shared/schemas/`, `README.md` hay `roadmap.md`.

## Trạng thái
| Ngày | Nội dung | Trạng thái |
|---|---|---|
| 2026-11-11 | Giai đoạn 1 (Mốc 1): schema SQLite, REST/WebSocket, prompt và tạo biên bản bằng OpenAI | Code xong, chờ mở PR |

## Cách chạy và kiểm tra bằng tay
PR không chứa test tự động, vì test của TV3 chỉ để trên máy người làm. Kiểm tra bằng tay như sau:
1. Dùng Python 3.11. Trong `services/backend` chạy `pip install -r requirements.txt` rồi `python main.py`.
2. Mở `http://127.0.0.1:8000/docs`.
3. Gọi `POST /recording/start` với `{"title": "Thử", "capture_mode": "room"}`, ghi lại `id` trả về.
4. Gọi `PUT /meetings/{id}/transcript` với một transcript theo `shared/schemas/transcript_contract.json`, trong đó `meeting_id` bằng `id` ở bước 3.
5. Gọi `GET /meetings/{id}/transcript` và `POST /speakers/confirm` để kiểm tra việc gán tên.
6. `POST /meetings/{id}/report/generate`:
   - Cần `OPENAI_API_KEY`. Không có khóa thì trả 503, đó là hành vi đúng.
   - Muốn tắt hẳn AI thì đặt `LLM_PROVIDER=none`.

## API mới
| Nhóm | Route |
|---|---|
| meetings | `GET /meetings` (trả mảng), `GET/DELETE /meetings/{id}`, `PUT/GET /meetings/{id}/transcript`, `GET /meetings/{id}/speakers`, `GET/PUT /meetings/{id}/report`, `POST /meetings/{id}/report/generate` |
| recording | `POST /recording/start`, `POST /recording/{id}/stop` (chưa nối `audio_engine`) |
| speakers | `GET /speakers`, `PATCH/DELETE /speakers/{id}`, `POST /speakers/confirm` |
| ws | `WS /ws`, sự kiện dạng `{type, meeting_id, data}` |

Mã lỗi:
- 404: không tìm thấy.
- 409: xung đột, hoặc chưa có transcript.
- 422: dữ liệu sai khuôn.
- 503: AI đang tắt, hoặc lỗi mạng có thể thử lại.
- 502: OpenAI từ chối yêu cầu.

## Biến môi trường
Xem `services/backend/.env.example`:
- `LLM_PROVIDER`, `LLM_MODEL` (mặc định `gpt-6-luna`), `LLM_REASONING_EFFORT`, `OPENAI_API_KEY`.
- `VOXSCRIBE_DATA_DIR`: thư mục chứa DB. Mặc định là `%LOCALAPPDATA%\VoxScribe`.

## Điểm cần chú ý khi merge
- **`services/backend/requirements.txt`:** xung đột với PR #1 của TV2 đã được giải quyết bằng commit merge `origin/dev` ngay trong nhánh này.
  - `requirements.txt` là bộ phát hành Hybrid: có `httpx`, `onnxruntime`, `openai`; không có `whisperx` hay `pyannote.audio`.
  - `requirements-offline.txt` chứa `sherpa-onnx`, `faster-whisper` và `tokenizers`. Đây là các thư viện cho STT offline và bộ thêm dấu câu của TV2 (bản Hybrid dùng Deepgram nên không cần chúng).
  - TV2 cần cài `-r requirements-offline.txt` để chạy pipeline sherpa-onnx.
- **CORS** giờ chỉ cho phép `http://localhost:5173`, `http://127.0.0.1:5173`, `http://tauri.localhost` và `tauri://localhost`. Cần TV1 xác nhận origin của Tauri.
- DB là file SQLite, được tạo hoặc nâng cấp lúc server khởi động.
  - Schema hiện tại là v2.
  - Mỗi bước nâng cấp chạy trọn trong một giao dịch: hoặc xong hết, hoặc không đổi gì.
  - Commit không chứa file DB (`*.db`) hay khóa API (`.env`).
- Mọi lệnh ghi dùng `BEGIN IMMEDIATE`, để bước kiểm tra và bước ghi không bị request khác chen vào giữa.
- Transcript và biên bản có số phiên bản (`revision`):
  - Biên bản có `stale = true` khi transcript đã đổi sau lúc tạo.
  - `POST /report/generate` trả 409 khi đang tạo trùng, hoặc khi transcript hay biên bản bị đổi trong lúc chờ LLM.
- Backend dùng Python 3.11.

## Ảnh hưởng tới thành viên khác
- **TV1:**
  - Gọi `GET /meetings` (trả mảng).
  - Kết thúc ghi bằng `POST /recording/{id}/stop`.
  - WebSocket phát `recording.status` khi bắt đầu và kết thúc ghi. Các loại sự kiện khác đã định nghĩa trong `core_app/api/websocket.py`.
- **TV2:**
  - TV3 đọc transcript theo contract hiện tại, có nhận thêm trường `words: [{word, start, end}]` nếu có.
  - `speaker_name` do bộ so khớp trả về chỉ được gán khi người đó đã có trong danh bạ.
  - Vector giọng gồm 192 số, lưu kèm `model_version`.
  - `find_closest_speakers` trong `repositories.py` dùng được để so khớp.
