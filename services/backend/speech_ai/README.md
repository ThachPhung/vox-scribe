# speech_ai — STT & tách giọng (C++/ONNX)

Không dùng PyTorch, không cần Hugging Face token. Toàn bộ chạy bằng ONNX Runtime qua `sherpa-onnx`.

| Bước | Model | Kích thước |
|---|---|---|
| VAD | Silero VAD | 0.6 MB |
| Phân đoạn giọng | `pyannote/segmentation-3.0` (ONNX) | 6 MB |
| Vân tay giọng (diarization + danh bạ) | 3D-Speaker CAM++ zh+en, **192 chiều** | 28 MB |
| STT tiếng Việt (mặc định) | Zipformer-vi int8 (2025-04-20) | 60 MB |
| STT dự phòng | faster-whisper int8 (`--backend whisper`) | tuỳ cỡ |
| Dấu câu + viết hoa | ViBERT-capu int8 (`welcomyou/vibert-capu-onnx`, CC-BY-SA-4.0) | 116 MB |

## Cài đặt (Python 3.11)

Cần `ffmpeg` trong PATH (Windows: `winget install ffmpeg`, macOS: `brew install ffmpeg`).

```bash
cd services/backend
uv venv --python 3.11 .venv
```

Kích hoạt venv: macOS/Linux `source .venv/bin/activate`, Windows `.venv\Scripts\activate`.
Không có `uv` thì dùng `py -3.11 -m venv .venv` (Windows) / `python3.11 -m venv .venv`, rồi `pip install` thay cho `uv pip install`.

```bash
uv pip install -r requirements-offline.txt
python ../../scripts/download_models.py
python ../../scripts/make_samples.py
```

- `download_models.py`: tải ~240 MB model ONNX vào `models/` (chỉ lần đầu).
- `make_samples.py`: tạo file thử vào `samples/` từ các đoạn giọng người thật công khai
  (repo không chứa file `.wav`).

## Chạy thử

Chạy trong `services/backend`, venv đã kích hoạt. Copy nguyên lệnh:

```bash
python -m speech_ai.pipeline_runner samples/meeting_vi.wav -o out_vi.json --words
```

Mono, 4 người nói tiếng Việt: ra 4 nhãn `SPEAKER_01..04`, chữ có dấu câu, kèm timestamp từng từ.

```bash
python -m speech_ai.pipeline_runner samples/meeting_stereo.wav -o out_stereo.json
```

Stereo như file của audio_engine (Trái = Mic, Phải = Loa): Mic -> `SPEAKER_00`, 2 người phía loa ->
`SPEAKER_01`, `SPEAKER_02`; tiếng loa vọng vào mic bị lọc bỏ (`mic_bleed_dropped` trong dòng thời gian).

Gán tên thật: enroll 2 người phía loa vào danh bạ rồi chạy lại.

```bash
python -m speech_ai.speaker_matcher enroll "Lôi Quân" samples/sr/leijun-sr-1.wav samples/sr/leijun-sr-2.wav
python -m speech_ai.speaker_matcher enroll "Lưu Đức Hoa" samples/sr/liudehua-sr-1.wav samples/sr/liudehua-sr-2.wav
python -m speech_ai.pipeline_runner samples/meeting_stereo.wav -o out_stereo.json --voicebook data/voicebook.json --mic-name "Thạch"
```

Kết quả: `speakers[]` có tên Thạch / Lôi Quân / Lưu Đức Hoa, điểm khớp ~0.8. Hai người phía loa nói
tiếng Trung nên phần chữ của họ không có nghĩa; file này chỉ để thử tách và nhận diện người nói.

Chạy với file của bạn: thay đường dẫn `samples/...` bằng file `.wav` / `.mp3` / `.m4a` bất kỳ.

### Tuỳ chọn

- `--channel auto` (mặc định): file 2 kênh -> chế độ stereo, 1 kênh -> mono. Có thể ép `mix|left|right|stereo`.
- Stereo: Kênh Trái -> `SPEAKER_00` (người dùng máy), lọc bỏ tiếng loa vọng vào mic (`--keep-bleed` để tắt).
  Kênh Phải -> gom cụm `SPEAKER_01, 02...`.
- `--num-speakers N`: số người ở Kênh Phải nếu biết trước. Không truyền thì tự đoán (`--merge-threshold`).
- `--voicebook`: danh bạ giọng để điền `speaker_name`; `--match-threshold` (mặc định 0.55).
- `--backend whisper --whisper-model small`: dùng faster-whisper (có dấu câu, chậm hơn).
- `--words`: kèm timestamp từng từ.
- `--no-punct`: tắt bước thêm dấu câu / viết hoa.

Đầu ra theo `shared/schemas/transcript_contract.json` (có thêm mảng `speakers` kèm vector 192 chiều
để UI enroll người lạ).

## Danh bạ giọng nói

```bash
python -m speech_ai.speaker_matcher enroll "Thạch" thach_1.wav thach_2.wav   # thêm / cập nhật
python -m speech_ai.speaker_matcher list
python -m speech_ai.speaker_matcher identify unknown.wav
python -m speech_ai.speaker_matcher remove <speaker_id>
```

Mặc định lưu ở `data/voicebook.json` (`JsonVoiceBook`, dùng tạm). core_app chỉ cần cài lớp có
cùng interface `VoiceBook` (`list / get / upsert / delete`) trên sqlite-vec rồi truyền vào `SpeakerMatcher`.

## Gom cụm người nói

1. sherpa-onnx: pyannote-segmentation-3.0 + CAM++ + FastClustering (hay tách thừa 1 người thành 2-3 cụm).
2. `refine_clusters`: tính lại vector cho cả cụm, gộp dần cặp giống nhất khi cosine ≥ 0.65 (hoặc tới
   đúng `--num-speakers`), cụm < 1s gán vào cụm gần nhất, đánh nhãn lại theo thứ tự xuất hiện.

Kết quả trên bộ test thật của sherpa-onnx (2-4 người, 16-57s): đúng số người 4/4 file, cả khi không
cho biết trước số người (trước refine: 1/4 file khi tự đoán).

| Model vân tay | Cùng người (min) | Khác người (max) | Nhận đúng |
|---|---|---|---|
| CAM++ 192 chiều (đang dùng) | 0.757 | 0.419 | 7/7 |
| WeSpeaker ResNet34 256 chiều | 0.832 | 0.882 (chồng lấn) | 7/7 |

## Lưu ý

- Zipformer-vi trả chữ IN HOA không dấu câu; `punctuator.py` (ViBERT-capu) thêm `, . ? :` và viết hoa
  tên riêng. Timestamp từng từ (`words`) vẫn giữ dạng chữ thường gốc từ STT.
- Model dấu câu dùng license CC-BY-SA-4.0: cần ghi nguồn (dragonSwing/vibert-capu) khi phát hành.
- Danh bạ giọng là dữ liệu sinh trắc học: `data/` đã nằm trong `.gitignore`, không commit lên repo.
- Lọc tiếng vọng mic hiện dựa trên đường bao năng lượng; nếu người dùng nói chồng lên loa thì vẫn giữ.

## Dùng chung DB với core_app + tự học giọng

```bash
python -m speech_ai.pipeline_runner meeting.wav --db <VOXSCRIBE_DATA_DIR>/voxscribe.db --meeting-id <id> --mic-name "Thạch"
```

- `--db`: so khớp tên từ bảng `voice_profiles` (thay cho `--voicebook` JSON) -> tên ra luôn có trong
  bảng `speakers`, core_app gán được ngay. Tự học bật mặc định, tắt bằng `--no-learn`.
- Schema v3 (`core_app/database/models.py`): bảng `voice_samples` lưu từng sample (`auto` / `manual`,
  `active` / `suspect`); `voice_profiles.embedding` = trung bình có trọng số các sample `active`
  (sample `manual` nặng gấp đôi, tối thiểu 30s). `/speakers/confirm` thêm sample `manual` thay vì ghi đè.

Luật tự học (`speech_ai/voice_learning.py`, `LearningPolicy`):

| Luật | Mặc định | Cờ CLI |
|---|---|---|
| Ngưỡng sàn số giây nói trong cuộc họp | 30s | `--min-learn-sec` |
| Sample tối đa / người / cuộc họp (mỗi sample ≥ 30s) | 2 | `--max-learn-samples` |
| Điểm khớp tối thiểu để tự ghi | 0.70 | |
| Người mới (< 5 sample) | 0.78 | |
| Phải hơn người giống thứ 2 | ≥ 0.10 | |
| Kiểm tra lệch | mỗi 5 cuộc họp có tự học | |
| Lệch khi | sample gần đây giống mỏ neo < 0.65 hoặc độ phân tán > 0.10 | |

Bị lệch -> sample tự học đáng ngờ chuyển `suspect` (không tính vào hồ sơ), **tạm dừng tự học**;
người dùng `/speakers/confirm` lại người đó -> thêm sample `manual` và bật lại tự học.
Người chưa có trong danh bạ không được tự tạo (không biết tên) -> cần `/speakers/confirm`.
