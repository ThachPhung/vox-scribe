"""Điều phối toàn bộ luồng từ file .wav ra JSON lời thoại.

    .wav ──load 16kHz──► WhisperX (chữ + timestamp từng từ)
                     └─► pyannote (ai nói lúc nào) ──► gán SPEAKER_xx ──► JSON

Đầu ra theo shared/schemas/transcript_contract.json.

Chạy thử (từ thư mục services/backend):
    python -m speech_ai.pipeline_runner samples/meeting.wav -o out.json --model small
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .audio_chunker import Channel, load_audio
from .diarizer import Diarizer, DiarizerConfig, assign_speakers
from .transcriber import Transcriber, TranscriberConfig, duration_sec


@dataclass
class PipelineResult:
    transcript: dict
    timings: dict[str, float] = field(default_factory=dict)


def to_contract(meeting_id: str, language: str | None, segments: list[dict]) -> dict:
    out = []
    for s in segments:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "start": round(float(s["start"]), 3),
                "end": round(float(s["end"]), 3),
                "speaker_label": s.get("speaker", "SPEAKER_UNKNOWN"),
                "speaker_name": None,  # speaker_matcher sẽ điền ở bước sau
                "text": text,
            }
        )
    return {"meeting_id": meeting_id, "language": language, "segments": out}


def run_pipeline(
    audio_path: str,
    meeting_id: str | None = None,
    channel: Channel = "mix",
    tcfg: TranscriberConfig | None = None,
    dcfg: DiarizerConfig | None = None,
    diarize: bool = True,
) -> PipelineResult:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    audio = load_audio(audio_path, channel=channel)
    timings["audio_sec"] = round(duration_sec(audio), 2)
    timings["load"] = round(time.perf_counter() - t0, 2)

    t = time.perf_counter()
    transcriber = Transcriber(tcfg)
    result = transcriber.transcribe(audio)
    timings["transcribe"] = round(time.perf_counter() - t, 2)

    if diarize:
        t = time.perf_counter()
        turns = Diarizer(dcfg).diarize(audio)
        result = assign_speakers(result, turns)
        timings["diarize"] = round(time.perf_counter() - t, 2)

    timings["total"] = round(time.perf_counter() - t0, 2)
    meeting_id = meeting_id or Path(audio_path).stem or str(uuid.uuid4())
    return PipelineResult(to_contract(meeting_id, result.get("language"), result["segments"]), timings)


def main() -> None:
    p = argparse.ArgumentParser(description="VoxScribe speech pipeline (WhisperX + pyannote)")
    p.add_argument("audio")
    p.add_argument("-o", "--out", help="File JSON đầu ra (mặc định in ra màn hình)")
    p.add_argument("--meeting-id")
    p.add_argument("--channel", choices=["mix", "left", "right"], default="mix")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--language", default="vi", help="'auto' để tự nhận diện")
    p.add_argument("--device", default="cpu", help="cpu | cuda (WhisperX)")
    p.add_argument("--compute-type", default=None, help="mặc định: cuda=float16, cpu=int8")
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--align-model", help="Tên model wav2vec2 trên HF để căn timestamp từng từ")
    p.add_argument("--diar-device", default=None, help="cpu | cuda | mps (mặc định = --device)")
    p.add_argument("--num-speakers", type=int)
    p.add_argument("--min-speakers", type=int)
    p.add_argument("--max-speakers", type=int)
    p.add_argument("--no-diarize", action="store_true")
    a = p.parse_args()

    tcfg = TranscriberConfig(
        model=a.model,
        language=None if a.language == "auto" else a.language,
        device=a.device,
        compute_type=a.compute_type or ("float16" if a.device == "cuda" else "int8"),
        batch_size=a.batch_size,
        align_model=a.align_model,
    )
    dcfg = DiarizerConfig(
        device=a.diar_device or a.device,
        num_speakers=a.num_speakers,
        min_speakers=a.min_speakers,
        max_speakers=a.max_speakers,
    )
    res = run_pipeline(a.audio, a.meeting_id, a.channel, tcfg, dcfg, diarize=not a.no_diarize)

    text = json.dumps(res.transcript, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"Đã ghi {a.out}")
    else:
        print(text)
    print("Thời gian (giây):", res.timings)


if __name__ == "__main__":
    main()
