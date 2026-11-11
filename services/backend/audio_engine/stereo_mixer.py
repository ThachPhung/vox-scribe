"""Đồng bộ hai luồng, bù clock drift và xuất WAV stereo 16 kHz.

Kênh trái là mic, kênh phải là âm thanh hệ thống (WASAPI loopback).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import numpy as np
import soundfile as sf
import soxr

from .models import AudioChunk, ChannelStats, RecordingResult

TARGET_RATE = 16_000
CHANNELS = 2  # left = mic, right = system audio


class ChunkSource(Protocol):
    """What StereoRecorder needs from a capture stream."""

    overflows: int

    @property
    def sample_rate(self) -> int: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def drain(self) -> list[AudioChunk]: ...


class ChannelAligner:
    """Resamples one source to 16 kHz and keeps it on the shared recording clock.

    Between chunks the source's own sample count is trusted. Each chunk's arrival
    time is compared with how much audio has been emitted so far (the "lag"):

    * a large lag means the source sent nothing for a while (WASAPI loopback
      delivers no data while nothing is playing), so the gap is filled with silence;
    * a small, persistent lag is clock drift between the sound card and the system
      clock. It is smoothed over many chunks and corrected in one step once it
      exceeds the tolerance, by inserting silence or dropping samples.
    """

    def __init__(
        self,
        source_rate: int,
        start_time: float,
        *,
        gap_threshold_sec: float = 0.2,
        drift_tolerance_sec: float = 0.04,
        smoothing: float = 0.05,
    ) -> None:
        self._resampler = soxr.ResampleStream(source_rate, TARGET_RATE, 1, dtype="float32")
        self._start_time = start_time
        self._gap_threshold = round(gap_threshold_sec * TARGET_RATE)
        self._drift_tolerance = drift_tolerance_sec * TARGET_RATE
        self._smoothing = smoothing
        self._lag_avg = 0.0
        self._pending_drop = 0
        self.position = 0  # samples emitted so far, at TARGET_RATE
        self.padded = 0
        self.dropped = 0

    def clock_position(self, t: float) -> int:
        """Sample index on the shared timeline for clock time `t`."""
        return round((t - self._start_time) * TARGET_RATE)

    def push(self, chunk: AudioChunk) -> np.ndarray:
        audio = self._resampler.resample_chunk(chunk.samples)
        expected_start = self.clock_position(chunk.captured_at) - len(audio)
        lag = expected_start - (self.position - self._pending_drop)

        pad = 0
        if lag > self._gap_threshold:
            pad, self._lag_avg = lag, 0.0
        else:
            self._lag_avg += self._smoothing * (lag - self._lag_avg)
            if abs(self._lag_avg) > self._drift_tolerance:
                correction, self._lag_avg = round(self._lag_avg), 0.0
                if correction > 0:
                    pad = correction
                else:
                    self._pending_drop -= correction
        return self._emit(audio, pad)

    def fill_until(self, position: int) -> np.ndarray:
        """Emit silence up to `position` if the source has fallen that far behind."""
        return self._emit(np.zeros(0, np.float32), max(0, position - self.position))

    def flush(self) -> np.ndarray:
        """Return audio still buffered in the resampler. Call once, at the end."""
        return self._emit(self._resampler.resample_chunk(np.zeros(0, np.float32), last=True), 0)

    def stats(self, overflows: int) -> ChannelStats:
        return ChannelStats(
            padded_sec=self.padded / TARGET_RATE,
            dropped_sec=self.dropped / TARGET_RATE,
            overflows=overflows,
        )

    def _emit(self, audio: np.ndarray, pad: int) -> np.ndarray:
        cancel = min(pad, self._pending_drop)
        pad -= cancel
        self._pending_drop -= cancel
        if self._pending_drop:
            drop = min(self._pending_drop, len(audio))
            audio = audio[drop:]
            self._pending_drop -= drop
            self.dropped += drop
        if pad:
            audio = np.concatenate((np.zeros(pad, np.float32), audio))
            self.padded += pad
        self.position += len(audio)
        return audio


class StereoRecorder:
    """Records the mic (left) and system audio (right) into one 16 kHz stereo WAV.

    Single use:
        recorder = StereoRecorder(MicRecorder(pa), LoopbackRecorder(pa), "meeting.wav")
        recorder.start()
        ...
        result = recorder.stop()
    """

    def __init__(
        self,
        mic: ChunkSource,
        loopback: ChunkSource,
        output_path: str | Path,
        *,
        meeting_id: str | None = None,
        poll_interval_sec: float = 0.1,
        silence_fill_delay_sec: float = 0.5,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.output_path = Path(output_path)
        self.meeting_id = meeting_id or uuid.uuid4().hex
        self._sources = (mic, loopback)
        self._poll_interval = poll_interval_sec
        self._fill_delay = round(silence_fill_delay_sec * TARGET_RATE)
        self._clock = clock
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopped = False
        self._error: BaseException | None = None
        self._file: sf.SoundFile | None = None
        self._aligners: tuple[ChannelAligner, ...] = ()
        self._pending = [np.zeros(0, np.float32) for _ in range(CHANNELS)]
        self._frames_written = 0
        self._started_at: datetime | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("StereoRecorder can only be started once")
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = sf.SoundFile(
            self.output_path, "w", samplerate=TARGET_RATE, channels=CHANNELS, subtype="PCM_16"
        )
        start_time = self._clock()
        self._started_at = datetime.now(timezone.utc)
        self._aligners = tuple(ChannelAligner(s.sample_rate, start_time) for s in self._sources)
        try:
            for source in self._sources:
                source.start()
        except BaseException:
            self._stop_sources()
            self._file.close()
            raise
        self._thread = threading.Thread(target=self._run, name="stereo-recorder", daemon=True)
        self._thread.start()

    def stop(self) -> RecordingResult:
        if self._thread is None:
            raise RuntimeError("StereoRecorder was not started")
        if self._stopped:
            raise RuntimeError("StereoRecorder is already stopped")
        self._stopped = True
        try:
            self._stop_sources()
            self._stop_event.set()
            self._thread.join()
            if self._error is not None:
                raise RuntimeError("Recording failed while writing audio") from self._error
            self._pump(final=True)
        finally:
            self._file.close()

        mic_stats, loopback_stats = (
            aligner.stats(source.overflows) for aligner, source in zip(self._aligners, self._sources)
        )
        return RecordingResult(
            meeting_id=self.meeting_id,
            file_path=str(self.output_path.resolve()),
            sample_rate=TARGET_RATE,
            channels=CHANNELS,
            started_at=self._started_at,
            duration_sec=self._frames_written / TARGET_RATE,
            mic=mic_stats,
            loopback=loopback_stats,
        )

    def _run(self) -> None:
        try:
            while not self._stop_event.wait(self._poll_interval):
                self._pump()
        except BaseException as exc:  # re-raised by stop()
            self._error = exc

    def _pump(self, *, final: bool = False) -> None:
        silence_until = self._aligners[0].clock_position(self._clock()) - self._fill_delay
        for channel, (source, aligner) in enumerate(zip(self._sources, self._aligners)):
            parts = [self._pending[channel]]
            parts += [aligner.push(chunk) for chunk in source.drain()]
            parts.append(aligner.flush() if final else aligner.fill_until(silence_until))
            self._pending[channel] = np.concatenate(parts)

        if final:  # the channel that went quiet first is padded to the full length
            longest = max(len(p) for p in self._pending)
            self._pending = [np.pad(p, (0, longest - len(p))) for p in self._pending]
        self._write(min(len(p) for p in self._pending))

    def _write(self, frames: int) -> None:
        if frames == 0:
            return
        stereo = np.column_stack([p[:frames] for p in self._pending])
        self._file.write(np.clip(stereo, -1.0, 1.0))
        self._pending = [p[frames:] for p in self._pending]
        self._frames_written += frames

    def _stop_sources(self) -> None:
        for source in self._sources:
            source.stop()
