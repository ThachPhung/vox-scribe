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

```bash
cd services/backend
uv venv --python 3.11 .venv && source .venv/bin/activate
uv pip install sherpa-onnx faster-whisper numpy soundfile
python ../../scripts/download_models.py
```

Cần `ffmpeg` trong PATH.

## Chạy thử

```bash
# File mono
python -m speech_ai.pipeline_runner samples/meeting.wav -o out.json --words
# File stereo của audio_engine (Trái = Mic, Phải = Loa) + gán tên từ danh bạ
python -m speech_ai.pipeline_runner meeting_stereo.wav -o out.json --voicebook data/voicebook.json --mic-name "Thạch"
```

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
