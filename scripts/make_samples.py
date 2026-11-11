"""Tạo file âm thanh mẫu để chạy thử speech_ai trên mọi máy (Windows / macOS / Linux).

Không commit file .wav vào repo; script này tải các đoạn giọng người thật công khai rồi ghép lại:
- Giọng tiếng Việt: `test_wavs` có sẵn trong model Zipformer-vi (cần chạy download_models.py trước)
  + `vi.wav` trong GitHub release của sherpa-onnx.
- Giọng người cho phần tách / nhận diện người nói: bộ test speaker-recognition của sherpa-onnx.

    python scripts/download_models.py
    python scripts/make_samples.py

Tạo ra trong services/backend/samples/:
    meeting_vi.wav       mono, 4 người nói tiếng Việt  -> thử chép lời
    meeting_stereo.wav   stereo như audio_engine (Trái = Mic, Phải = Loa)
                         Mic: 1 người nói tiếng Việt (+ tiếng loa vọng vào mic)
                         Loa: 2 người (Lôi Quân, Lưu Đức Hoa) nói xen kẽ
    sr/*.wav             đoạn giọng riêng từng người để thử enroll danh bạ giọng
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "services" / "backend"
OUT = BACKEND / "samples"
VI_MODEL_WAVS = BACKEND / "models" / "sherpa-onnx-zipformer-vi-int8-2025-04-20" / "test_wavs"
GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SR = 16_000

SR_CLIPS = [
    "leijun-sr-1", "leijun-sr-2", "leijun-test-sr-1", "leijun-test-sr-2", "leijun-test-sr-3",
    "liudehua-sr-1", "liudehua-sr-2", "liudehua-test-sr-1", "liudehua-test-sr-2",
    "fangjun-sr-1", "fangjun-sr-2", "fangjun-sr-3", "fangjun-test-sr-1", "fangjun-test-sr-2",
]


def fetch(url: str, dst: Path) -> Path:
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"  ↓ {url}")
    tmp = dst.with_suffix(".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        f.write(r.read())
    tmp.replace(dst)
    return dst


def read16k(path: Path) -> np.ndarray:
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    if sr != SR:
        raise SystemExit(f"{path} có sample rate {sr}, cần {SR}")
    return audio.mean(axis=1)


def place(buf: np.ndarray, clip: np.ndarray, at_sec: float) -> float:
    i = int(at_sec * SR)
    n = min(len(clip), len(buf) - i)
    buf[i : i + n] += clip[:n]
    return at_sec + len(clip) / SR


def main() -> None:
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT, help=f"Thư mục ghi file (mặc định {OUT})")
    OUT = ap.parse_args().out
    vi_local = [VI_MODEL_WAVS / f"{i}.wav" for i in range(3)]
    if not all(p.exists() for p in vi_local):
        raise SystemExit(f"Không thấy {VI_MODEL_WAVS}. Chạy trước: python scripts/download_models.py")

    print("• Tải đoạn giọng mẫu")
    vi_main = fetch(f"{GH}/asr-models/vi.wav", OUT / "src" / "vi.wav")
    for name in SR_CLIPS:
        fetch(f"{GH}/speaker-recongition-models/{name}.wav", OUT / "sr" / f"{name}.wav")

    # 1) Mono tiếng Việt, 4 người
    clips = [read16k(p) for p in (vi_local[0], vi_main, vi_local[1], vi_local[2])]
    gap = np.zeros(int(0.8 * SR), np.float32)
    mono = np.concatenate([x for c in clips for x in (c, gap)])
    sf.write(OUT / "meeting_vi.wav", mono, SR, subtype="PCM_16")
    print(f"✓ meeting_vi.wav ({len(mono) / SR:.1f}s, mono, 4 người nói tiếng Việt)")

    # 2) Stereo như audio_engine
    total = 46.0
    left = np.zeros(int(total * SR), np.float32)
    right = np.zeros(int(total * SR), np.float32)
    mic = read16k(vi_main)
    plan = [
        (left, mic, 0.5),
        (right, OUT / "sr" / "leijun-test-sr-1.wav", 6.0),
        (left, mic, 15.5),  # Mic luôn là 1 người (người dùng máy này)
        (right, OUT / "sr" / "liudehua-test-sr-1.wav", 19.5),
        (right, OUT / "sr" / "leijun-test-sr-2.wav", 24.5),
        (right, OUT / "sr" / "liudehua-test-sr-2.wav", 32.5),
        (left, mic, 37.5),
    ]
    for buf, clip, at in plan:
        place(buf, read16k(clip) if isinstance(clip, Path) else clip, at)
    delay = int(0.03 * SR)
    left[delay:] += 0.25 * right[:-delay]  # tiếng loa vọng vào mic (không đeo tai nghe)
    stereo = np.stack([left, right], axis=1).clip(-1, 1)
    sf.write(OUT / "meeting_stereo.wav", stereo, SR, subtype="PCM_16")
    print(f"✓ meeting_stereo.wav ({total:.0f}s, stereo: Trái = Mic, Phải = Loa)")
    print(f"✓ sr/ ({len(SR_CLIPS)} đoạn giọng để enroll)")
    print(f"\nFile nằm tại: {OUT}")


if __name__ == "__main__":
    sys.exit(main())
