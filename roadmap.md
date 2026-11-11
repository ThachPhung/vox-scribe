# Roadmap VoxScribe

VoxScribe là ứng dụng Windows ghi âm cuộc họp, chép lời tiếng Việt, nhận diện người nói và tạo biên bản. Ưu tiên phát hành bản **Hybrid** cho laptop văn phòng RAM 8 GB dùng đồ họa tích hợp. Bản ghi và hồ sơ giọng được lưu trên máy. Người dùng chọn xử lý cloud cho từng cuộc họp trước khi ứng dụng gửi âm thanh đi.

## Hai chế độ xử lý

### Hybrid — bản phát hành đầu tiên

- **Chép lời và phân tách người nói.** Thử Deepgram Nova-3 cho tiếng Việt (`vi`), mốc từng từ và nhãn người nói trên bản ghi. Groq `whisper-large-v3-turbo` là phương án thử nghiệm chép lời có mốc từ, cần ghép với nguồn nhãn người nói riêng trước khi dùng thay Deepgram. [Deepgram — ngôn ngữ](https://developers.deepgram.com/docs/models-languages-overview), [Deepgram — diarization](https://developers.deepgram.com/docs/diarization), [Groq — Speech to Text](https://console.groq.com/docs/speech-to-text)
- **Nhận diện tên trên máy.** Dùng ECAPA-TDNN với ONNX Runtime CPU để trích xuất vector. So khớp tên và lưu hồ sơ giọng trong SQLite. [ONNX Runtime — cài đặt CPU](https://onnxruntime.ai/docs/install/#install-onnx-runtime-cpu)
- **Bộ cài cơ bản tối đa 150 MB là mục tiêu phát hành.** Build từ môi trường riêng, loại PyTorch, CUDA, WhisperX và `pyannote.audio` khỏi gói. Đo riêng dung lượng model giọng nếu tải sau.
- **Khi mất mạng**, vẫn ghi, lưu và phát lại WAV. Tác vụ chép lời chờ kết nối hoặc người dùng bấm thử lại.

### Offline — gói tùy chọn sau Hybrid

- **Chép lời và phân tách người nói.** Thử `whisper.cpp` với model Whisper đa ngôn ngữ đã lượng tử hóa và `sherpa-onnx` để phân tách người nói. Lấy CPU làm cấu hình chuẩn. Thử chạy chép lời và phân tách nối tiếp, giới hạn số luồng CPU. Kiểm tra riêng độ chính xác của mốc từ vì tính năng này của `whisper.cpp` còn ở mức thử nghiệm. [whisper.cpp — lượng tử hóa](https://github.com/ggml-org/whisper.cpp#quantization), [whisper.cpp — mốc từ](https://github.com/ggml-org/whisper.cpp#word-level-timestamp-experimental), [sherpa-onnx — diarization](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html)
- **Model tải theo nhu cầu hoặc cài từ gói riêng.** Dùng chung luồng ONNX và SQLite của bản Hybrid. Sau khi có model, ghi âm, chép lời, nhận diện và xuất transcript phải chạy được khi ngắt mạng. Chốt kích thước model và số luồng CPU sau khi đo trên laptop 8 GB.
- **Báo cáo cục bộ.** Chế độ này tắt LLM cloud và webhook. Người dùng có thể chỉnh biên bản và xuất trên máy. Tổng hợp biên bản bằng AI offline cần đánh giá LLM cục bộ riêng.

## Phân công theo thư mục

| Thành viên | Phạm vi phụ trách | Kết quả bàn giao |
|---|---|---|
| **TV1 — Desktop Frontend & Windows Audio** | [`services/backend/audio_engine/`](services/backend/audio_engine/), [`apps/desktop-ui/`](apps/desktop-ui/), [`scripts/build_windows.ps1`](scripts/build_windows.ps1) | Thu âm hai kênh, giao diện chọn cách xử lý, bộ cài Windows nhẹ |
| **TV2 — Speech & Voice Biometrics AI** | [`services/backend/speech_ai/`](services/backend/speech_ai/), [`scripts/download_models.py`](scripts/download_models.py) | Chép lời tiếng Việt, phân tách người nói, nhận diện giọng trên CPU và đánh giá phương án Offline |
| **TV3 — Backend, Database & LLM Agent** | [`services/backend/core_app/`](services/backend/core_app/), [`services/backend/main.py`](services/backend/main.py), [`services/backend/requirements.txt`](services/backend/requirements.txt) | Quản lý tác vụ, kết nối API, lưu trữ, tạo và xuất biên bản |

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
| `src/components/RecorderBar.tsx`, `src/hooks/useAudioStream.ts` | Làm thanh thu âm với chọn thiết bị, bắt đầu, tạm dừng, kết thúc và waveform thời gian thực. Cho người dùng chọn gửi bản ghi để chép lời, thông báo nhà cung cấp và hiển thị trạng thái tải lên, xử lý, chờ mạng hoặc thử lại. |
| `src/components/TranscriptView.tsx` | Hiển thị lời thoại và tua đến mốc `start` trên WAV gốc khi bấm vào câu. |
| `src/components/SpeakerTagModal.tsx`, `src/components/VoiceBookPage.tsx` | Phát đoạn mẫu 5 giây của giọng lạ khi có mẫu phù hợp, nhập hoặc chọn tên thật, quản lý danh bạ giọng nói và làm mới transcript sau khi xác nhận. |
| `src/components/ReportEditor.tsx`, `src/hooks/useMeetings.ts` | Hiển thị lịch sử họp, xem, chỉnh sửa và xuất biên bản qua API của TV3. |
| `src/services/apiClient.ts` | Quản lý kết nối REST/WebSocket phía giao diện và cập nhật theo giao diện API đã chốt với TV3. |
| `src-tauri/`, `scripts/build_windows.ps1` | Làm System Tray và thông báo Zoom/Teams. Dùng PyInstaller đóng gói backend Python từ bộ phụ thuộc phát hành, dùng Tauri tạo bộ cài `.exe`/`.msi`. Kiểm tra Visual C++ Runtime và WebView2 trên Windows sạch, chọn cách cấp runtime cho máy cài qua mạng và máy cài offline. Đo dung lượng bộ cài, dung lượng sau cài và phần tải thêm. [ONNX Runtime — yêu cầu Windows](https://onnxruntime.ai/docs/install/#requirements), [Tauri — WebView2](https://v2.tauri.app/distribute/windows-installer/#webview2-installation-options) |

**Nghiệm thu** khi máy Windows x64 sạch, RAM 8 GB và dùng đồ họa tích hợp cài được ứng dụng, thu đúng hai kênh trong cuộc họp dài, hiện waveform và phát lại đúng mốc. Kiểm tra chọn cloud, mất mạng và thử lại ngay trên giao diện.

## TV2 — Chép lời, phân tách và so khớp giọng

### `services/backend/speech_ai/` và `scripts/download_models.py`

| Tệp | Công việc |
|---|---|
| `transcriber.py` | Tích hợp Deepgram cho bản Hybrid qua REST bằng `httpx`. Dùng Nova-3 với `language=vi` và bật diarization cho bản ghi. Chuyển kết quả thành transcript chung có mốc từng từ. Giữ giao diện này để nối `whisper.cpp` khi triển khai Offline. |
| `audio_chunker.py`, `pipeline_runner.py` | Đọc WAV stereo, chuẩn bị âm thanh theo kênh và giữ mốc gốc. Ở chế độ tai nghe đã xác nhận, gán lời thoại kênh trái cho chủ máy và chỉ phân tách người nói ở kênh phải. Ở chế độ phòng họp, kiểm tra kênh mic và tiếng vọng giữa hai kênh. Thử FLAC khi cần giảm dung lượng tải lên. Nếu phải chia file dài, ghép lại mốc thời gian và đối chiếu nhãn giữa các phần. |
| `diarizer.py` | Chuẩn hóa nhãn trả về từ Deepgram thành `SPEAKER_00`, `SPEAKER_01`… trong phạm vi một cuộc họp, giữ thông tin nói chồng khi nguồn có trả về. Với Offline, thử `sherpa-onnx` để tạo khoảng thời gian theo người nói rồi gắn nhãn vào transcript. |
| `embedder.py` | Lấy đoạn giọng sạch dài 3–10 giây từ WAV gốc, ưu tiên đoạn không chồng tiếng. Chạy ECAPA-TDNN ONNX bằng `onnxruntime` CPU, kiểm tra tiền xử lý, đầu ra 192 chiều và độ tương đương với model gốc. Vector và mẫu giọng dùng để định danh được xử lý trên máy. |
| `speaker_matcher.py` | So cosine giữa vector cùng phiên bản model. Bắt đầu thử với ngưỡng `0.75`, đo nhận nhầm và bỏ sót trước khi chốt. Trả `UNKNOWN` nếu dưới ngưỡng hoặc thiếu mẫu phù hợp. Tính vector trung bình cập nhật khi người dùng xác nhận giọng để TV3 lưu. |
| `scripts/download_models.py` | Ghim phiên bản, nguồn, checksum, giấy phép phân phối và dung lượng của model ECAPA-TDNN. Quản lý riêng model ASR và diarization của Offline. Bàn giao cho TV1 và TV3 cách tìm model, tải theo nhu cầu hoặc nhập từ gói cài sẵn. |

**Nghiệm thu** khi bản Hybrid cho transcript tiếng Việt có mốc từng từ và nhãn người nói trên cả mẫu họp online dùng tai nghe lẫn họp trực tiếp. Kiểm tra đối chiếu giọng trên CPU, nhãn `UNKNOWN`, xác nhận tên và tương thích hồ sơ giọng khi đổi model. Giữ WhisperX và `pyannote.audio` trong môi trường thử nghiệm để làm mốc so sánh.

## TV3 — Điều phối, lưu trữ và biên bản

### `services/backend/core_app/` và `services/backend/main.py`

| Tệp hoặc thư mục | Công việc |
|---|---|
| `database/connection.py`, `database/models.py`, `database/repositories.py` | Lưu cuộc họp, câu thoại, tác vụ xử lý và hồ sơ giọng trong SQLite. Dùng sqlite-vec để lưu và truy vấn vector kèm phiên bản model. Khi xác nhận tên, cập nhật câu theo nhãn trong đúng cuộc họp và lưu vector do TV2 tính trong cùng giao dịch. |
| `api/routes_recording.py` | Nối điều khiển thu âm với `audio_engine`. Lưu WAV trước, tạo tác vụ cloud sau khi người dùng chọn. Quản lý chờ mạng, hủy và thử lại theo từng cuộc họp để tránh tạo transcript trùng. Cấu hình khóa API ở backend ngoài bộ cài. |
| `api/routes_meetings.py`, `api/routes_speakers.py` | Cung cấp API danh sách cuộc họp, transcript, phát bản ghi và mẫu giọng, xác nhận tên, quản lý danh bạ và tạo hoặc xuất biên bản. |
| `api/websocket.py`, `services/backend/main.py` | Lắp các router FastAPI và đẩy waveform, trạng thái thu, tiến độ tải lên và xử lý AI, lỗi và sự kiện Zoom/Teams để UI hiển thị. |
| `llm_agent/summarizer.py`, `llm_agent/action_extractor.py`, `llm_agent/prompts/` | Ghép transcript theo dạng `[00:12:05] Anh Nam: Nội dung phát biểu...`. Dùng prompt tiếng Việt để tạo bốn phần gồm mục tiêu, quyết định, vấn đề còn bỏ ngỏ và bảng phân công. Giữ đúng tên và đánh dấu thông tin còn thiếu. Với cuộc họp 2–3 giờ, dùng Map–Reduce hoặc cửa sổ ngữ cảnh lớn và kiểm tra các ý đầu, giữa, cuối. Cấu hình LLM độc lập với nhà cung cấp chép lời. Chỉ gửi transcript cho LLM cloud khi người dùng chọn tạo biên bản theo cách này. |
| `exporters/docx_exporter.py`, `exporters/pdf_md_exporter.py`, `exporters/` | Xuất Word `.docx` với bảng biểu hành chính, PDF và Markdown. Tích hợp tùy chọn gửi báo cáo qua webhook Notion/Slack theo cấu hình. |

**Nghiệm thu** khi tác vụ vẫn có thể thử lại sau khi mất mạng hoặc mở lại ứng dụng, transcript chỉ lưu một lần, tên đã xác nhận cập nhật đúng và báo cáo xuất được ba định dạng. Kiểm tra tạo báo cáo cloud và webhook riêng theo lựa chọn của người dùng.

## Điểm bàn giao giữa ba phần

| Điểm bàn giao | Nội dung cần thống nhất trước khi tích hợp |
|---|---|
| **TV1 → TV2** qua [`audio_contract.json`](shared/schemas/audio_contract.json) | Dùng `meeting_id`, `file_path`, `sample_rate=16000`, `channels=2` và thứ tự trái/mic, phải/hệ thống. Giữ `started_at` và `duration_sec` theo schema. Chốt cách truyền chế độ tai nghe và thông tin chủ máy. |
| **TV2 → TV3** qua [`transcript_contract.json`](shared/schemas/transcript_contract.json) | Giữ `start`/`end` cấp câu, `speaker_label`, `speaker_name` và `text`. Chốt trường mốc từng từ và cách biểu thị khi nguồn xử lý chỉ có mốc cấp câu. Mọi mốc tính bằng giây từ đầu WAV. Nhãn người nói duy nhất trong phạm vi cuộc họp. |
| **TV2 ↔ TV3** khi xác nhận giọng | TV2 tạo mẫu, so khớp và tính vector cập nhật. TV3 lưu hồ sơ kèm phiên bản model, cập nhật câu thoại theo `meeting_id` và `speaker_label`. Chốt cách trả đoạn mẫu 5 giây và tránh cập nhật vector hai lần nếu gửi lại cùng xác nhận. |
| **TV3 ↔ TV1** qua REST/WebSocket | TV3 viết server, TV1 viết phía giao diện. Dùng các nhóm route `/recording`, `/meetings`, `/speakers` và WebSocket `/ws`. Chốt cách chọn chế độ, xác nhận gửi cloud, hiển thị tiến độ, lỗi, chờ mạng và thử lại. |

## Ai cập nhật cấu hình và tệp dùng chung

| Tệp hoặc nhóm tệp | Người sửa chính | Người cần phối hợp |
|---|---|---|
| `shared/schemas/audio_contract.json` | TV1 | TV2 duyệt phần đọc âm thanh, TV3 duyệt nếu luồng điều phối thay đổi. |
| `shared/schemas/transcript_contract.json` | TV2 | TV3 duyệt phần lưu và trả kết quả, TV1 duyệt nếu dữ liệu hiển thị thay đổi. |
| `services/backend/requirements.txt`, `services/backend/main.py` và cấu hình nhà cung cấp | TV3 | TV2 bàn giao `httpx`, `onnxruntime` CPU, `numpy` và `soundfile` cho Hybrid, cùng phiên bản đã thử trên Windows. TV3 tách phụ thuộc Offline và PoC khỏi môi trường phát hành Hybrid. TV1 kiểm tra lại khi đóng gói. |
| `apps/desktop-ui/package.json`, lockfile, `apps/desktop-ui/src-tauri/`, `scripts/build_windows.ps1` | TV1 | TV2 và TV3 bàn giao cách tìm model, khởi chạy backend và tài nguyên cần đóng gói. |
| `scripts/download_models.py` | TV2 | TV1 dùng khi đóng gói, TV3 dùng khi cấu hình backend. |

- Mỗi người tạo nhánh tính năng từ `dev`, chia PR theo phần mình phụ trách và tích hợp trên `dev` trước khi đưa tính năng lên `main`.
- Khi đổi tệp dùng chung, người phụ trách cập nhật và gửi kèm dữ liệu mẫu cho bên sử dụng duyệt. Tách phần đổi giao diện dữ liệu khỏi phần triển khai để các bên cập nhật theo cùng một phiên bản.
- Dùng một WAV stereo, một transcript JSON và mẫu sự kiện REST/WebSocket để các phần phát triển song song.

## Đo hiệu năng trước khi phát hành

| Hạng mục | Cách kiểm tra |
|---|---|
| **Cài đặt** | TV1 thử trên Windows x64 sạch, Core i3 hoặc Ryzen 3, RAM 8 GB, đồ họa tích hợp. Ghi model CPU, dung lượng `.exe`/`.msi`, dung lượng sau cài và phần tải thêm. |
| **Tốc độ và tài nguyên** | TV2 và TV3 đo từ lúc bấm chép lời đến khi transcript sẵn sàng với bản ghi 1 giờ và một mẫu 2–3 giờ. Tách thời gian chuẩn bị, tải lên, chép lời và nhận diện cục bộ. Ghi điều kiện mạng, RAM đỉnh và mức CPU. TV1 kiểm tra giao diện và thu âm vẫn phản hồi khi có tác vụ nền và Teams/Zoom đang chạy. |
| **Chất lượng tiếng Việt** | TV2 dùng cùng tập mẫu họp online, họp phòng và có người nói chồng để so sánh với PoC. Đo tỷ lệ lỗi từ (WER) với cùng cách chuẩn hóa, sai lệch mốc thời gian, lỗi gán người nói và tỷ lệ nhận nhầm tên. |
| **Khả năng phục hồi** | TV1 và TV3 thử mất mạng giữa lúc tải lên, hủy, thử lại và khởi động lại ứng dụng. Với Offline, ngắt mạng sau khi cài model rồi chạy trọn luồng ghi âm, chép lời, nhận diện và xuất transcript. |

Chốt thời gian xử lý, mức RAM, dung lượng model và ngưỡng chất lượng theo kết quả đo trên máy mục tiêu. Dùng các số đó để quyết định phát hành gói Offline và công bố cấu hình hỗ trợ.

## Thứ tự triển khai

| Mốc | Công việc song song | Điều kiện hoàn thành |
|---|---|---|
| **1. Chốt giao diện và chạy thử Hybrid** | TV1 chuẩn bị WAV stereo và cấu hình máy 8 GB. TV2 thử Deepgram với tiếng Việt và nạp ECAPA-TDNN ONNX trên CPU. TV3 chốt schema, mẫu REST/WebSocket và bộ phụ thuộc phát hành với TV1, TV2. | Có transcript mẫu với mốc từ và nhãn người nói, vector ONNX hợp lệ và dữ liệu mẫu để cả nhóm làm song song. |
| **2. Nối luồng ghi âm đến phát lại** | TV1 hoàn thành ghi âm, chọn cloud và tua theo câu. TV2 hoàn thành chuẩn hóa kết quả. TV3 nối tác vụ nền, tiến độ và lưu transcript. | Từ UI có thể ghi, chọn chép lời và bấm câu để nghe đúng đoạn. Bản ghi phát lại được khi mất mạng. |
| **3. Nhận diện tên, xuất báo cáo và phát hành Hybrid** | TV1 hoàn thành màn hình giọng lạ và bộ cài. TV2 hoàn thành so khớp và đo chất lượng. TV3 nối cập nhật tên, biên bản và xuất file. | Đo trên máy Windows 8 GB và đạt tiêu chí phát hành của nhóm. Xác nhận tên cập nhật đúng câu, báo cáo lấy tên mới và xuất được. |
| **4. Đánh giá và phát hành gói Offline** | TV2 thử model đa ngôn ngữ đã lượng tử hóa và diarization CPU. TV1 kiểm tra cài gói riêng. TV3 kiểm tra điều phối, lưu và xuất cục bộ. | Chạy được khi ngắt mạng và đạt ngưỡng chất lượng, RAM, thời gian xử lý đã chốt cho máy mục tiêu. |
