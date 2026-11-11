"""Script tải sẵn model AI về máy trong lần cài đầu tiên.

Tất cả model ONNX lấy từ GitHub release chính thức của k2-fsa/sherpa-onnx
(không cần Hugging Face token).

    python scripts/download_models.py               # tải bộ mặc định
    python scripts/download_models.py --whisper small  # tải thêm faster-whisper (int8)

Model được lưu vào services/backend/models/ (đã có trong .gitignore).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "services" / "backend" / "models"
GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

# name -> (url, loại: "tar" giải nén thư mục | "file" giữ nguyên)
MODELS = {
    # STT tiếng Việt: Zipformer transducer, int8, ~60MB
    "sherpa-onnx-zipformer-vi-int8-2025-04-20": (
        f"{GH}/asr-models/sherpa-onnx-zipformer-vi-int8-2025-04-20.tar.bz2",
        "tar",
    ),
    # Phân đoạn giọng nói: pyannote/segmentation-3.0 bản ONNX, ~7MB
    "sherpa-onnx-pyannote-segmentation-3-0": (
        f"{GH}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
        "tar",
    ),
    # Vân tay giọng nói (embedding) dùng cho gom cụm người nói + speaker_matcher, ~26MB
    "wespeaker_en_voxceleb_resnet34_LM.onnx": (
        f"{GH}/speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx",
        "file",
    ),
    # VAD lọc khoảng lặng, ~0.6MB
    "silero_vad.onnx": (f"{GH}/asr-models/silero_vad.onnx", "file"),
}


def _download(url: str, dst: Path) -> None:
    print(f"  ↓ {url}")
    with urllib.request.urlopen(url) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                sys.stdout.write(f"\r    {done / 1e6:6.1f} / {total / 1e6:.1f} MB")
                sys.stdout.flush()
    print()


def fetch(name: str, url: str, kind: str, force: bool = False) -> None:
    target = MODELS_DIR / name
    if target.exists() and not force:
        print(f"✓ {name} (đã có)")
        return
    print(f"• {name}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_file = Path(tmp) / Path(url).name
        _download(url, tmp_file)
        if kind == "file":
            shutil.move(tmp_file, target)
            return
        extract_dir = Path(tmp) / "x"
        with tarfile.open(tmp_file, "r:bz2") as tar:
            tar.extractall(extract_dir, filter="data")
        src = extract_dir / name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(src, target)


def fetch_whisper(size: str) -> None:
    from faster_whisper import download_model

    out = MODELS_DIR / f"faster-whisper-{size}"
    print(f"• faster-whisper-{size}")
    download_model(size, output_dir=str(out))
    print(f"✓ {out}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Tải lại kể cả khi đã có")
    p.add_argument("--whisper", metavar="SIZE", help="Tải thêm faster-whisper (tiny/base/small/medium/large-v3-turbo)")
    a = p.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name, (url, kind) in MODELS.items():
        fetch(name, url, kind, a.force)
    if a.whisper:
        fetch_whisper(a.whisper)
    print(f"\nModel nằm tại: {MODELS_DIR}")


if __name__ == "__main__":
    main()
