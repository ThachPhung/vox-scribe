"""Điều phối toàn bộ luồng từ file .wav ra JSON lời thoại.

    .wav ─► load 16kHz mono
          ├─► [diarize] sherpa-onnx (pyannote-seg-3.0 + WeSpeaker) ─► các lượt nói SPEAKER_xx
          │        └─► lượt dài > max_sec được Silero VAD cắt nhỏ
          └─► [không diarize] Silero VAD ─► các đoạn có tiếng nói
    các đoạn ─► STT (Zipformer-vi int8 | faster-whisper int8)
            ─► thêm dấu câu + viết hoa (ViBERT-capu ONNX) ─► JSON

Đầu ra theo shared/schemas/transcript_contract.json.

Chạy thử (từ thư mục services/backend):
    python -m speech_ai.pipeline_runner samples/meeting.wav -o out.json --num-speakers 2
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .audio_chunker import SAMPLE_RATE, AudioChunk, Channel, VadSegmenter, load_audio, split_fixed
from .diarizer import Diarizer, DiarizerConfig, merge_turns
from .punctuator import Punctuator
from .transcriber import DEFAULT_MODELS_DIR, Utterance, create_transcriber

UNKNOWN = "SPEAKER_UNKNOWN"
DEFAULT_VAD = DEFAULT_MODELS_DIR / "silero_vad.onnx"


@dataclass
class PipelineConfig:
    backend: str = "sherpa"  # sherpa | whisper
    whisper_model: str = "small"
    language: str | None = "vi"
    diarize: bool = True
    num_speakers: int | None = None
    cluster_threshold: float = 0.5
    max_segment_sec: float = 20.0
    batch_size: int = 16
    num_threads: int | None = None
    include_words: bool = False
    punctuate: bool = True  # backend whisper đã có dấu câu sẵn -> bỏ qua


@dataclass
class PipelineResult:
    transcript: dict
    timings: dict[str, float] = field(default_factory=dict)


def _build_chunks(
    audio: np.ndarray, cfg: PipelineConfig, vad: VadSegmenter, timings: dict
) -> list[tuple[str, AudioChunk]]:
    if not cfg.diarize:
        return [(UNKNOWN, c) for c in vad.segment(audio)]

    t = time.perf_counter()
    diarizer = Diarizer(
        DiarizerConfig(
            num_speakers=cfg.num_speakers,
            threshold=cfg.cluster_threshold,
            num_threads=cfg.num_threads,
        )
    )
    turns = merge_turns(diarizer.diarize(audio))
    timings["diarize"] = round(time.perf_counter() - t, 2)

    chunks: list[tuple[str, AudioChunk]] = []
    for turn in turns:
        a, b = int(turn.start * SAMPLE_RATE), int(turn.end * SAMPLE_RATE)
        piece = audio[a:b]
        if len(piece) == 0:
            continue
        if turn.end - turn.start <= cfg.max_segment_sec:
            parts = [AudioChunk(turn.start, piece)]
        else:
            parts = vad.segment(piece, offset=turn.start) or split_fixed(piece, turn.start, cfg.max_segment_sec)
        chunks += [(turn.speaker, p) for p in parts]
    return chunks


def _to_contract(meeting_id: str, language: str | None, items: list[tuple[str, Utterance]], words: bool) -> dict:
    segments = []
    for speaker, u in items:
        if not u.text:
            continue
        seg = {
            "start": round(u.start, 3),
            "end": round(u.end, 3),
            "speaker_label": speaker,
            "speaker_name": None,  # speaker_matcher sẽ điền ở bước sau
            "text": u.text,
        }
        if words:
            seg["words"] = [{k: round(v, 3) if isinstance(v, float) else v for k, v in asdict(w).items()} for w in u.words]
        segments.append(seg)
    return {"meeting_id": meeting_id, "language": language, "segments": segments}


def run_pipeline(
    audio_path: str,
    meeting_id: str | None = None,
    channel: Channel = "mix",
    cfg: PipelineConfig | None = None,
) -> PipelineResult:
    cfg = cfg or PipelineConfig()
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    audio = load_audio(audio_path, channel=channel)
    timings["audio_sec"] = round(len(audio) / SAMPLE_RATE, 2)

    vad = VadSegmenter(str(DEFAULT_VAD), max_speech_sec=cfg.max_segment_sec)
    chunks = _build_chunks(audio, cfg, vad, timings)

    t = time.perf_counter()
    stt = create_transcriber(
        cfg.backend, whisper_model=cfg.whisper_model, language=cfg.language, num_threads=cfg.num_threads
    )
    timings["load_stt"] = round(time.perf_counter() - t, 2)

    t = time.perf_counter()
    items: list[tuple[str, Utterance]] = []
    for i in range(0, len(chunks), cfg.batch_size):
        batch = chunks[i : i + cfg.batch_size]
        utts = stt.transcribe_many([c for _, c in batch])
        items += [(spk, u) for (spk, _), u in zip(batch, utts)]
    timings["transcribe"] = round(time.perf_counter() - t, 2)

    if cfg.punctuate and cfg.backend == "sherpa" and items:
        t = time.perf_counter()
        texts = Punctuator(num_threads=cfg.num_threads).punctuate_many([u.text for _, u in items])
        for (_, u), text in zip(items, texts):
            u.text = text
        timings["punctuate"] = round(time.perf_counter() - t, 2)

    timings["total"] = round(time.perf_counter() - t0, 2)
    timings["rtf"] = round(timings["total"] / max(timings["audio_sec"], 1e-6), 3)  # < 1 là nhanh hơn thời gian thực
    meeting_id = meeting_id or Path(audio_path).stem
    return PipelineResult(_to_contract(meeting_id, cfg.language, items, cfg.include_words), timings)


def main() -> None:
    p = argparse.ArgumentParser(description="VoxScribe speech pipeline (sherpa-onnx / faster-whisper)")
    p.add_argument("audio")
    p.add_argument("-o", "--out", help="File JSON đầu ra (mặc định in ra màn hình)")
    p.add_argument("--meeting-id")
    p.add_argument("--channel", choices=["mix", "left", "right"], default="mix")
    p.add_argument("--backend", choices=["sherpa", "whisper"], default="sherpa")
    p.add_argument("--whisper-model", default="small", help="tiny/base/small/medium/large-v3-turbo")
    p.add_argument("--language", default="vi")
    p.add_argument("--no-diarize", action="store_true")
    p.add_argument("--num-speakers", type=int, help="Số người nói nếu biết trước")
    p.add_argument("--threshold", type=float, default=0.5, help="Ngưỡng gom cụm khi không biết số người")
    p.add_argument("--max-segment", type=float, default=20.0, help="Độ dài tối đa 1 đoạn đưa vào STT (giây)")
    p.add_argument("--threads", type=int)
    p.add_argument("--words", action="store_true", help="Kèm timestamp từng từ trong JSON")
    p.add_argument("--no-punct", action="store_true", help="Không thêm dấu câu / viết hoa")
    a = p.parse_args()

    cfg = PipelineConfig(
        backend=a.backend,
        whisper_model=a.whisper_model,
        language=a.language,
        diarize=not a.no_diarize,
        num_speakers=a.num_speakers,
        cluster_threshold=a.threshold,
        max_segment_sec=a.max_segment,
        num_threads=a.threads,
        include_words=a.words,
        punctuate=not a.no_punct,
    )
    res = run_pipeline(a.audio, a.meeting_id, a.channel, cfg)

    text = json.dumps(res.transcript, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"Đã ghi {a.out}")
    else:
        print(text)
    print("Thời gian (giây):", res.timings)


if __name__ == "__main__":
    main()
