# speech_ai — STT & tách giọng (C++/ONNX)

Không dùng PyTorch, không cần Hugging Face token. Toàn bộ chạy bằng ONNX Runtime qua `sherpa-onnx`.

| Bước | Model | Kích thước |
|---|---|---|
| VAD | Silero VAD | 0.6 MB |
| Phân đoạn giọng | `pyannote/segmentation-3.0` (ONNX) | 6 MB |
| Embedding giọng | WeSpeaker ResNet34-LM (ONNX) | 26 MB |
| STT tiếng Việt (mặc định) | Zipformer-vi int8 (2025-04-20) | 60 MB |
| STT dự phòng | faster-whisper int8 (`--backend whisper`) | tuỳ cỡ |

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
python -m speech_ai.pipeline_runner samples/meeting.wav -o out.json --num-speakers 2 --words
```

- `--num-speakers N`: biết trước số người thì nên truyền (chính xác hơn). Không truyền thì dùng `--threshold`.
- `--channel left|right`: chỉ lấy kênh Mic / Loa từ file stereo của audio_engine.
- `--backend whisper --whisper-model small`: dùng faster-whisper (có dấu câu, chậm hơn).
- `--words`: kèm timestamp từng từ.

Đầu ra theo `shared/schemas/transcript_contract.json`.

## Lưu ý

- Zipformer-vi trả chữ không dấu câu; pipeline chuẩn hoá về chữ thường + viết hoa đầu đoạn.
