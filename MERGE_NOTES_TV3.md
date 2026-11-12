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
  - Schema hiện tại là v4 (v3 đến từ PR #7 của TV2, v4 là phần tuần 2 của TV3).
  - Mỗi bước nâng cấp chạy trọn trong một giao dịch: hoặc xong hết, hoặc không đổi gì.
  - Commit không chứa file DB (`*.db`) hay khóa API (`.env`).
- Mọi lệnh ghi dùng `BEGIN IMMEDIATE`, để bước kiểm tra và bước ghi không bị request khác chen vào giữa.
- Transcript và biên bản có số phiên bản (`revision`):
  - Biên bản có `stale = true` khi transcript đã đổi sau lúc tạo.
  - `POST /report/generate` trả 409 khi đang tạo trùng, hoặc khi transcript hay biên bản bị đổi trong lúc chờ LLM.
- Backend dùng Python 3.11.

## Tuần 2 (commit sau PR #3)
- **Schema v4** (tự nâng cấp khi server khởi động, chạy sau v3 của PR #7):
  - `meeting_speakers` lưu channel, duration_sec, vector và model từ `speakers[]` của TV2.
  - `voice_samples` (bảng của PR #7) không đổi cột, chỉ thêm index duy nhất `uq_voice_samples_confirmation`: mỗi nhãn đã xác nhận của một cuộc họp có đúng một mẫu `manual`.
- **`PUT /meetings/{id}/transcript`** nhận contract mới có `speakers[]`. Transcript kiểu cũ vẫn nhận được.
- **`POST /speakers/confirm`** chỉ nhận tên; trường `embedding` đã bỏ. Vector lấy từ `speakers[]` của transcript đã lưu.
- **`GET /speakers`** trả kèm `voiceprints`. **`GET /meetings/{id}/speakers`** có thêm `channel`, `duration_sec`, `has_meeting_embedding`.
- **Biên bản:** prompt `report-vi-v2`; khuôn structured outputs có mô tả cho từng trường.
- **Xuất Word:** `GET /meetings/{id}/report/export?format=docx`, theo thể thức hành chính, kèm bảng phân công.
- **Kiểm tra bằng tay:** nạp transcript → tạo hoặc sửa biên bản → mở `/docs`, gọi route export, tải file `.docx` về rồi mở bằng Word.

## Tuần 2: thay đổi hành vi cần biết khi merge
- **Nạp lại transcript thì bỏ các xác nhận tên cũ của cuộc họp đó, kể cả mẫu giọng `manual` đã học từ chúng.** Tên được gán lại theo `speakers[].name` của bộ so khớp; người dùng xác nhận lại thì mẫu được học lại.
- **Xác nhận một tên mà bộ so khớp đã gán đúng** vẫn lưu mẫu giọng nhưng không làm biên bản thành stale.
- **`GET /speakers`:** mỗi phần tử `voiceprints` có thêm `auto_learn` (`on` hoặc `paused`) và `paused_reason`, để giao diện nhắc người dùng xác nhận lại khi tự học bị tạm dừng.
- **WebSocket:** client gửi không kịp trong 2 giây hoặc lỗi sẽ bị đóng với mã 1011. Giao diện cần tự nối lại khi nhận mã này.
- **`POST /report/generate`:** biên bản bị cắt giữa chừng hoặc sai khuôn trả 502, không còn 500.
- **`PUT /meetings/{id}/report`** nhận body mới: `{content, expected_revision, transcript_revision}`. Gửi bằng `revision` cũ thì nhận 409.
- **Mã lỗi:** quá tải tạo biên bản hoặc DB bận trả 503. Tạo trùng hoặc dữ liệu đổi trong lúc chờ LLM trả 409.
- **`LLM_REASONING_EFFORT`** mặc định là `low`.

## Gộp với PR #7 của TV2 (tự học vân tay giọng)
Nhánh này đã chứa các commit của PR #7 (`thachpv-dev`, tới `ba42188`) và sửa phần `core_app` cho khớp.
- **Số schema:** v3 của PR #7 giữ nguyên văn. Phần của TV3 là v4, chạy sau v3.
- **Một bảng mẫu giọng, một hàm tính hồ sơ:** `/speakers/confirm` ghi mẫu `manual` vào `voice_samples` của PR #7 rồi gọi `voice_profiles.recompute_profile` và `set_auto_learn`. Không còn hàm tính riêng trong `repositories.py`.
- **Một `SqliteVoiceBook`:** chỉ còn lớp trong `speech_ai/voice_learning.py`. Lớp cùng tên trong `repositories.py` đã bỏ.
- **Phần thay cho đoạn PR #7 sửa trong `repositories.py`:** `_save_voice_profile` và trường `embedding` của confirm không còn. Thay vào đó:
  - Mẫu xác nhận tay gắn với (cuộc họp, nhãn). Sửa nhãn sang người khác thì mẫu chuyển theo và hồ sơ của cả hai người được tính lại.
  - Sau khi nhãn được xác nhận là người Y, các mẫu `auto` **cùng giọng** trong cuộc họp đó (cosine từ 0.55 với vector của nhãn) được xử lý lại: của Y thì `active`, của người khác thì `suspect`. Tìm theo giọng chứ không theo nhãn, vì nhãn `SPEAKER_xx` đổi giữa các lần chạy pipeline. Dòng `suspect` được giữ để hạn mức mỗi cuộc họp vẫn tính.
  - Xác nhận lại một người (kể cả khi nhãn đã xác nhận rồi) bật lại tự học cho người đó.
- **DB đã lên v3 theo PR #7** nâng tiếp lên v4 bình thường.
- **Thứ tự merge:** PR #7 đã merge vào `dev` (`fc63654`). Xung đột của nó với `dev` chỉ là hai dòng ví dụ lệnh `--db` trong chú thích đầu file `speech_ai/pipeline_runner.py`, đã giữ theo nhánh `thachpv-dev`. Nhánh này đã merge `dev` mới, nên PR chỉ còn phần `core_app` của TV3.
- **TV3 đã sửa hai chỗ trong `core_app/database/voice_profiles.py` của PR #7** (TV2 xem giúp, cả hai đều nằm trong `weighted_centroid`):
  - Mẫu `manual` tính theo số giây thật nhân 2. Mức 30 giây chỉ còn dùng khi không rõ số giây (hồ sơ có từ trước v3), vì confirm giờ lấy số giây từ transcript. Hằng số đổi tên từ `MANUAL_MIN_SEC` thành `MANUAL_UNKNOWN_SEC`.
  - Khi các mẫu triệt tiêu nhau (tổng gần vector 0) hàm trả `None`, nên hồ sơ bị xóa thay vì lưu một vector toàn số 0.
- **Gợi ý còn lại cho TV2** (TV3 không sửa `speech_ai`): `SqliteVoiceBook.upsert` tìm tên phân biệt hoa thường, trong khi `core_app` coi "nam" và "Nam" là một người.

## Ảnh hưởng tới thành viên khác
- **TV1:**
  - Gọi `GET /meetings` (trả mảng).
  - Kết thúc ghi bằng `POST /recording/{id}/stop`.
  - WebSocket phát `recording.status` khi bắt đầu và kết thúc ghi. Các loại sự kiện khác đã định nghĩa trong `core_app/api/websocket.py`.
- **TV2:**
  - TV3 đọc transcript theo contract hiện tại, có nhận thêm trường `words: [{word, start, end}]` nếu có.
  - `speaker_name` do bộ so khớp trả về chỉ được gán khi người đó đã có trong danh bạ.
  - Vector giọng gồm 192 số, lưu kèm `model_version`.
  - So khớp và tự học đi qua `speech_ai/voice_learning.py`; `repositories.py` không còn hàm so khớp.
