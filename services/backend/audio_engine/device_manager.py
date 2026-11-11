"""Liệt kê và chọn microphone, thiết bị phát và đầu vào WASAPI Loopback tương ứng."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pyaudiowpatch as pyaudio

from .models import AudioDevice

LOOPBACK_SUFFIX = " [Loopback]"


@contextmanager
def open_audio() -> Iterator[pyaudio.PyAudio]:
    """PyAudio session that is always terminated, even on errors."""
    pa = pyaudio.PyAudio()
    try:
        yield pa
    finally:
        pa.terminate()


def list_microphones(pa: pyaudio.PyAudio) -> list[AudioDevice]:
    return [
        _to_device(info, "maxInputChannels")
        for info in _wasapi_devices(pa)
        if info["maxInputChannels"] > 0 and not _is_loopback(info)
    ]


def list_speakers(pa: pyaudio.PyAudio) -> list[AudioDevice]:
    return [
        _to_device(info, "maxOutputChannels")
        for info in _wasapi_devices(pa)
        if info["maxOutputChannels"] > 0
    ]


def list_loopbacks(pa: pyaudio.PyAudio) -> list[AudioDevice]:
    return [_to_device(info, "maxInputChannels") for info in _wasapi_devices(pa) if _is_loopback(info)]


def default_microphone(pa: pyaudio.PyAudio) -> AudioDevice:
    return _default_device(pa, "defaultInputDevice", "maxInputChannels", "microphone")


def default_speaker(pa: pyaudio.PyAudio) -> AudioDevice:
    return _default_device(pa, "defaultOutputDevice", "maxOutputChannels", "speaker")


def get_microphone(pa: pyaudio.PyAudio, index: int) -> AudioDevice:
    return _find(list_microphones(pa), index, "microphone")


def get_speaker(pa: pyaudio.PyAudio, index: int) -> AudioDevice:
    return _find(list_speakers(pa), index, "speaker")


def loopback_for(pa: pyaudio.PyAudio, speaker: AudioDevice) -> AudioDevice:
    """Loopback input that captures what `speaker` plays."""
    candidates = [lb for lb in list_loopbacks(pa) if lb.name.startswith(speaker.name)]
    if not candidates:
        raise RuntimeError(f"No WASAPI loopback found for speaker {speaker.name!r}")
    exact = speaker.name + LOOPBACK_SUFFIX
    return next((lb for lb in candidates if lb.name == exact), candidates[0])


def _wasapi_devices(pa: pyaudio.PyAudio) -> list[dict[str, Any]]:
    host_index = _wasapi(pa)["index"]
    infos = (pa.get_device_info_by_index(i) for i in range(pa.get_device_count()))
    return [info for info in infos if info["hostApi"] == host_index]


def _wasapi(pa: pyaudio.PyAudio) -> dict[str, Any]:
    try:
        return pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError as exc:
        raise RuntimeError("WASAPI is not available on this system") from exc


def _default_device(pa: pyaudio.PyAudio, key: str, channels_key: str, kind: str) -> AudioDevice:
    index = _wasapi(pa)[key]
    if index < 0:
        raise RuntimeError(f"Windows has no default {kind}")
    return _to_device(pa.get_device_info_by_index(index), channels_key)


def _find(devices: list[AudioDevice], index: int, kind: str) -> AudioDevice:
    for device in devices:
        if device.index == index:
            return device
    raise ValueError(f"No WASAPI {kind} with index {index}")


def _is_loopback(info: dict[str, Any]) -> bool:
    return bool(info.get("isLoopbackDevice", False))


def _to_device(info: dict[str, Any], channels_key: str) -> AudioDevice:
    return AudioDevice(
        index=int(info["index"]),
        name=str(info["name"]),
        channels=int(info[channels_key]),
        sample_rate=int(info["defaultSampleRate"]),
        is_loopback=_is_loopback(info),
    )
