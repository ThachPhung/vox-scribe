# Roadmap VoxScribe

VoxScribe là ứng dụng Windows ghi âm cuộc họp, chép lời tiếng Việt, nhận diện người nói và tạo biên bản. Quy trình mặc định chạy cục bộ. Groq Whisper và gửi báo cáo qua webhook là các tùy chọn tích hợp.

## Phân công theo thư mục

| Thành viên | Phạm vi phụ trách | Kết quả bàn giao |
|---|---|---|
| **TV1 — Desktop Frontend & Windows Audio** | [`services/backend/audio_engine/`](services/backend/audio_engine/), [`apps/desktop-ui/`](apps/desktop-ui/), [`scripts/build_windows.ps1`](scripts/build_windows.ps1) | Thu âm hai kênh, giao diện desktop, bộ cài Windows |
| **TV2 — Speech & Voice Biometrics AI** | [`services/backend/speech_ai/`](services/backend/speech_ai/), [`scripts/download_models.py`](scripts/download_models.py) | Bản chép lời có mốc từng từ, nhãn người nói và kết quả so khớp giọng |
| **TV3 — Backend, Database & LLM Agent** | [`services/backend/core_app/`](services/backend/core_app/), [`services/backend/main.py`](services/backend/main.py), [`services/backend/requirements.txt`](services/backend/requirements.txt) | Điều phối qua REST và WebSocket, lưu trữ, tạo và xuất biên bản |

## TV1 — Thu âm Windows, giao diện và bộ cài

### `services/backend/audio_engine/`

| Tệp | Công việc |
|---|---|
| `device_manager.py` | Liệt kê và chọn microphone, thiết bị phát và đầu vào WASAPI Loopback tương ứng. |
| `mic_recorder.py`, `loopback_recorder.py` | Dùng PyAudioWPatch để thu đồng thời mic và âm thanh hệ thống qua WASAPI Loopback, không cần cáp âm thanh ảo. |
| `denoiser.py` | Tích hợp RNNoise cho kênh mic để giảm tiếng quạt và tiếng gõ phím. |
| `stereo_mixer.py` | Đồng bộ hai luồng, bù clock drift và xuất WAV stereo 16 kHz, kênh trái là mic, kênh phải là âm thanh hệ thống. |
| `process_watcher.py` | Phát hiện khi Zoom hoặc Teams mở và phát sự kiện để desktop hiện thông báo. |

### `apps/desktop-ui/` và `scripts/build_windows.ps1`

| Tệp hoặc thư mục | Công việc |
|---|---|
| `src/components/RecorderBar.tsx`, `src/hooks/useAudioStream.ts` | Làm thanh thu âm nhỏ gọn với chọn thiết bị, bắt đầu, tạm dừng, kết thúc, waveform thời gian thực và trạng thái xử lý. |
| `src/components/TranscriptView.tsx` | Hiển thị lời thoại và tua đến mốc `start` khi bấm vào câu. Dùng cùng bản WAV làm mốc cho kết quả chép lời. |
| `src/components/SpeakerTagModal.tsx`, `src/components/VoiceBookPage.tsx` | Phát đoạn mẫu 5 giây của giọng lạ khi có mẫu phù hợp, nhập hoặc chọn tên thật, quản lý danh bạ giọng nói và làm mới transcript sau khi xác nhận. |
| `src/components/ReportEditor.tsx`, `src/hooks/useMeetings.ts` | Hiển thị lịch sử họp, xem, chỉnh sửa và xuất biên bản qua API của TV3. |
| `src/services/apiClient.ts` | Quản lý kết nối REST/WebSocket phía giao diện và cập nhật theo giao diện API đã chốt với TV3. |
| `src-tauri/`, `scripts/build_windows.ps1` | Làm System Tray và thông báo Zoom/Teams. Dùng PyInstaller đóng gói backend Python và Tauri đóng gói desktop thành bộ cài `.exe`/`.msi`. Phối hợp TV2 để ứng dụng tìm và nạp được model sau khi cài. |

**Nghiệm thu** khi thu được mic và âm hệ thống trên Windows, kiểm tra đúng hai kênh và độ lệch khi thu dài, thấy waveform và thông báo, bấm câu để nghe lại và xác nhận được giọng lạ. Kiểm tra bộ cài trên máy Windows sạch.

## TV2 — Chép lời, phân tách và so khớp giọng

### `services/backend/speech_ai/` và `scripts/download_models.py`

| Tệp | Công việc |
|---|---|
| `transcriber.py` | Chép lời tiếng Việt bằng WhisperX và căn chỉnh tới từng từ. Với phương án Groq Whisper API, giữ cùng định dạng đầu ra và vẫn chạy bước căn chỉnh từ. |
| `audio_chunker.py`, `pipeline_runner.py` | Đọc WAV stereo và giữ mốc thời gian gốc qua các bước cắt và xử lý kênh. Khi chế độ họp online dùng tai nghe đã được xác nhận, gán lời thoại kênh trái cho chủ máy và bỏ qua bước phân tách người nói trên kênh này. |
| `diarizer.py` | Dùng `pyannote.audio` để gán nhãn `SPEAKER_00`, `SPEAKER_01`… cho lời thoại trong phòng họp hoặc trên kênh hệ thống. Giữ thông tin khoảng thời gian có người nói chồng lấn. |
| `embedder.py` | Chọn đoạn giọng sạch dài 3–10 giây, ưu tiên đoạn không có người khác nói chồng, và trích xuất vector ECAPA-TDNN 192 chiều. |
| `speaker_matcher.py` | So cosine với hồ sơ giọng lấy qua TV3. Điểm cao nhất `>= 0.75` thì gán tên tương ứng, dưới ngưỡng hoặc chưa có mẫu thì trả `UNKNOWN`. Tính vector trung bình cập nhật khi người dùng xác nhận giọng để TV3 lưu. |
| `scripts/download_models.py` | Chuẩn bị model cần cho chép lời, căn chỉnh, diarization và embedding. Bàn giao cho TV1 và TV3 vị trí model và cách nạp model. |

**Nghiệm thu** khi mẫu tiếng Việt có mốc từng từ, cuộc họp nhiều người có nhãn theo người nói và pipeline xử lý được cả chế độ tai nghe lẫn chế độ phòng họp. Kiểm tra so khớp ở hai phía ngưỡng `0.75` và cập nhật vector sau xác nhận.

## TV3 — Lưu trữ, API và biên bản

### `services/backend/core_app/` và `services/backend/main.py`

| Tệp hoặc thư mục | Công việc |
|---|---|
| `database/connection.py`, `database/models.py`, `database/repositories.py` | Lưu cuộc họp, câu thoại, mốc thời gian và hồ sơ giọng trong SQLite. Tích hợp sqlite-vec để lưu và truy vấn vector. Khi xác nhận tên, cập nhật toàn bộ câu thuộc nhãn đó trong đúng cuộc họp và lưu vector do TV2 tính trong cùng giao dịch. |
| `api/routes_recording.py` | Nối điều khiển thu âm với `audio_engine`. Khi kết thúc, chuyển thông tin bản ghi cho `speech_ai` và theo dõi kết quả xử lý. |
| `api/routes_meetings.py`, `api/routes_speakers.py` | Cung cấp API danh sách cuộc họp, transcript, phát bản ghi và mẫu giọng, xác nhận tên, quản lý danh bạ và tạo hoặc xuất biên bản. |
| `api/websocket.py`, `services/backend/main.py` | Lắp các router FastAPI và đẩy waveform, trạng thái thu âm, tiến độ AI và sự kiện phát hiện Zoom/Teams để UI hiển thị. |
| `llm_agent/summarizer.py`, `llm_agent/action_extractor.py`, `llm_agent/prompts/` | Ghép transcript theo dạng `[00:12:05] Anh Nam: Nội dung phát biểu...`. Dùng prompt tiếng Việt để tạo bốn phần gồm mục tiêu, quyết định đã chốt, vấn đề còn bỏ ngỏ và bảng phân công công việc. Ghi đúng người được giao, giữ tên đã xác nhận và đánh dấu khi transcript thiếu người phụ trách hoặc hạn hoàn thành. Với cuộc họp 2–3 giờ, dùng Map–Reduce hoặc cửa sổ ngữ cảnh lớn và kiểm tra các ý đầu, giữa, cuối cuộc họp. |
| `exporters/docx_exporter.py`, `exporters/pdf_md_exporter.py`, `exporters/` | Xuất Word `.docx` với bảng biểu hành chính, PDF và Markdown. Tích hợp tùy chọn gửi báo cáo qua webhook Notion/Slack theo cấu hình. |

**Nghiệm thu** khi có thể xử lý một cuộc họp từ REST/WebSocket, xem lại transcript sau khi mở lại ứng dụng, xác nhận tên và thấy các câu liên quan được cập nhật. Báo cáo có đủ bốn phần, đúng người phụ trách và xuất được Word, PDF, Markdown. Kiểm tra webhook khi có cấu hình đích.

## Điểm bàn giao giữa ba phần

| Điểm bàn giao | Nội dung cần thống nhất trước khi tích hợp |
|---|---|
| **TV1 → TV2** qua [`audio_contract.json`](shared/schemas/audio_contract.json) | Dùng `meeting_id` của cuộc họp, `file_path`, `sample_rate=16000`, `channels=2` và thứ tự trái/mic, phải/hệ thống. Giữ `started_at` và `duration_sec` theo schema. Chốt cách truyền chế độ tai nghe và thông tin chủ máy trước khi bật tối ưu kênh trái. |
| **TV2 → TV3** qua [`transcript_contract.json`](shared/schemas/transcript_contract.json) | Schema hiện có mốc `start`/`end` cấp câu, `speaker_label`, `speaker_name` và `text`. Bổ sung định dạng mốc từng từ trước khi tích hợp. Mọi mốc tính bằng giây từ đầu WAV. Nhãn người nói dùng trong phạm vi cuộc họp, thống nhất cách ánh xạ nhãn sang hồ sơ giọng và đánh dấu `UNKNOWN` trước khi UI hiển thị. |
| **TV2 ↔ TV3** khi xác nhận giọng | TV2 phụ trách tạo mẫu, so khớp và tính vector cập nhật. TV3 phụ trách đọc, ghi hồ sơ và cập nhật câu thoại theo `meeting_id` và `speaker_label`. Chốt cách trả đoạn mẫu 5 giây và hành vi khi người dùng gửi lại cùng một xác nhận. |
| **TV3 ↔ TV1** qua REST/WebSocket | TV3 viết server ở `core_app/api/`, TV1 viết phần gọi API ở `apps/desktop-ui/`. Thống nhất mẫu dữ liệu cho thu âm, waveform, tiến độ, thông báo, phát lại và gán tên. Repo đã có các nhóm route `/recording`, `/meetings`, `/speakers` và WebSocket `/ws`. |

## Ai cập nhật cấu hình và tệp dùng chung

| Tệp hoặc nhóm tệp | Người sửa chính | Người cần phối hợp |
|---|---|---|
| `shared/schemas/audio_contract.json` | TV1 | TV2 duyệt phần đọc âm thanh, TV3 duyệt nếu luồng điều phối thay đổi. |
| `shared/schemas/transcript_contract.json` | TV2 | TV3 duyệt phần lưu và trả kết quả, TV1 duyệt nếu dữ liệu hiển thị thay đổi. |
| `services/backend/requirements.txt`, `services/backend/main.py` | TV3 | TV1 và TV2 gửi tên thư viện, phiên bản cần dùng và yêu cầu riêng trên Windows qua PR hoặc issue. TV3 gom thay đổi, TV1 kiểm tra lại khi đóng gói. |
| `apps/desktop-ui/package.json`, lockfile, `apps/desktop-ui/src-tauri/`, `scripts/build_windows.ps1` | TV1 | TV2 và TV3 bàn giao yêu cầu model, cách khởi chạy backend và tài nguyên cần đóng gói. |
| `scripts/download_models.py` | TV2 | TV1 dùng khi đóng gói, TV3 dùng khi cấu hình backend. |

- Mỗi người tạo nhánh tính năng từ `dev`, chia PR theo phần mình phụ trách và tích hợp trên `dev` trước khi đưa tính năng lên `main`.
- Khi cần đổi một tệp dùng chung, báo người phụ trách tệp và đính kèm dữ liệu mẫu. Người phụ trách cập nhật tệp và nhờ bên đọc dữ liệu duyệt trước khi hợp nhất PR. Tách phần đổi giao diện trao đổi dữ liệu khỏi phần triển khai để các bên có thể cập nhật theo cùng một phiên bản.
- Mỗi mô-đun có thể phát triển với dữ liệu mẫu của bên bàn giao. Dùng một WAV stereo và một transcript JSON đã thống nhất để cả nhóm kiểm tra nối luồng.

## Thứ tự triển khai

| Mốc | Công việc song song | Điều kiện hoàn thành |
|---|---|---|
| **1. Chốt giao diện giữa các phần** | TV1 chuẩn bị WAV stereo mẫu, TV2 chuẩn bị transcript mẫu có mốc từ, TV3 chuẩn bị mẫu REST/WebSocket để TV1 dựng giao diện. | Cả ba bên đồng ý định dạng mẫu và chạy được phần của mình với dữ liệu mẫu. |
| **2. Nối luồng ghi âm đến phát lại** | TV1 hoàn thành thu âm và tua theo câu. TV2 hoàn thành chép lời và gán nhãn. TV3 nối API, tiến độ và lưu transcript. | Từ UI có thể ghi một cuộc họp tiếng Việt, thấy transcript có người nói và bấm câu để nghe lại đúng đoạn. |
| **3. Xác nhận danh tính và tạo báo cáo** | TV1 hoàn thành màn hình giọng lạ. TV2 hoàn thành so khớp và cập nhật embedding. TV3 nối cập nhật tên, tổng hợp và xuất biên bản. | Xác nhận tên một lần cập nhật các câu liên quan, lần ghi tiếp theo có thể nhận diện giọng đã lưu, báo cáo lấy tên mới. |
| **4. Kiểm thử và phát hành Windows** | TV1 đóng gói bộ cài. TV2 kiểm tra nạp model và luồng tai nghe/phòng họp. TV3 kiểm tra lưu trữ, báo cáo cuộc họp dài và đầu ra xuất file. | Cài trên Windows sạch và chạy trọn luồng ghi âm, chép lời, gán tên, xem lại và xuất biên bản. |
