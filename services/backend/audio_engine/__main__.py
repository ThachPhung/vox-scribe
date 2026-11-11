"""Chạy thử thu âm hai kênh từ dòng lệnh.

    cd services/backend
    python -m audio_engine devices
    python -m audio_engine record -o recordings/test.wav -d 30
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .device_manager import (
    default_microphone,
    default_speaker,
    get_microphone,
    get_speaker,
    list_microphones,
    list_speakers,
    open_audio,
)
from .loopback_recorder import LoopbackRecorder
from .mic_recorder import MicRecorder
from .models import AudioDevice
from .stereo_mixer import StereoRecorder

if TYPE_CHECKING:
    import pyaudiowpatch as pyaudio


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    with open_audio() as pa:
        if args.command == "devices":
            _print_devices(pa)
        else:
            _record(pa, args)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m audio_engine",
        description="Record microphone (left) + system audio (right) to a 16 kHz stereo WAV.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="list microphones and speakers")
    record = commands.add_parser("record", help="record mic + system audio")
    record.add_argument("-o", "--output", type=Path, default=Path("recordings/recording.wav"))
    record.add_argument("-d", "--duration", type=float, help="seconds to record (default: until Ctrl+C)")
    record.add_argument("--mic", type=int, metavar="INDEX", help="microphone index (default: Windows default)")
    record.add_argument("--speaker", type=int, metavar="INDEX", help="speaker index (default: Windows default)")
    return parser.parse_args(argv)


def _print_devices(pa: pyaudio.PyAudio) -> None:
    sections = (
        ("Microphones -> left channel", list_microphones(pa), default_microphone),
        ("Speakers -> right channel (captured via loopback)", list_speakers(pa), default_speaker),
    )
    for title, devices, get_default in sections:
        default_index = _default_index(pa, get_default)
        print(title)
        for device in devices:
            mark = "*" if device.index == default_index else " "
            print(f"  {mark} [{device.index:>3}] {device.name} ({device.sample_rate} Hz, {device.channels} ch)")
        print()
    print("* = Windows default")


def _default_index(
    pa: pyaudio.PyAudio, get_default: Callable[[pyaudio.PyAudio], AudioDevice]
) -> int | None:
    try:
        return get_default(pa).index
    except RuntimeError:
        return None


def _record(pa: pyaudio.PyAudio, args: argparse.Namespace) -> None:
    mic = MicRecorder(pa, None if args.mic is None else get_microphone(pa, args.mic))
    loopback = LoopbackRecorder(pa, None if args.speaker is None else get_speaker(pa, args.speaker))
    recorder = StereoRecorder(mic, loopback, args.output)

    print(f"Left  (mic):    {mic.device.name} @ {mic.sample_rate} Hz")
    print(f"Right (system): {loopback.device.name} @ {loopback.sample_rate} Hz")
    print("Recording... Ctrl+C to stop" if args.duration is None else f"Recording {args.duration:g} s...")

    recorder.start()
    try:
        deadline = None if args.duration is None else time.perf_counter() + args.duration
        while deadline is None or time.perf_counter() < deadline:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        result = recorder.stop()

    print(f"\nSaved {result.file_path} ({result.duration_sec:.1f} s)")
    for name, stats in (("mic", result.mic), ("system", result.loopback)):
        print(
            f"  {name:<6} padded {stats.padded_sec:.2f} s, "
            f"dropped {stats.dropped_sec:.2f} s, overflows {stats.overflows}"
        )
    print(json.dumps(result.to_contract(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
