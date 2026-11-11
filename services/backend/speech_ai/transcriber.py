"""Chuyển âm thanh thành chữ + timestamp từng từ.

Hai backend, cùng một interface `transcribe(chunk) -> Utterance`:

- "sherpa"  (mặc định): Zipformer tiếng Việt int8 chạy qua sherpa-onnx (C++/ONNX Runtime).
             Nhanh, nhẹ (~60MB), timestamp từng token có sẵn. Chữ ra IN HOA, không dấu câu
             -> được chuẩn hoá về chữ thường + viết hoa đầu câu.
- "whisper": faster-whisper (CTranslate2, int8). Chậm hơn nhưng có dấu câu và số.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .audio_chunker import SAMPLE_RATE, AudioChunk

DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
DEFAULT_SHERPA_MODEL = "sherpa-onnx-zipformer-vi-int8-2025-04-20"


@dataclass
class Word:
    word: str
    start: float
    end: float


@dataclass
class Utterance:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


def _pick(model_dir: Path, prefix: str) -> str:
    """Chọn file <prefix>*.onnx, ưu tiên bản int8."""
    files = sorted(model_dir.glob(f"{prefix}*.onnx"))
    if not files:
        raise FileNotFoundError(f"Không thấy {prefix}*.onnx trong {model_dir}. Chạy scripts/download_models.py")
    int8 = [f for f in files if ".int8." in f.name]
    return str((int8 or files)[0])


def _normalize_vi(text: str) -> str:
    text = " ".join(text.split()).lower()
    return text[:1].upper() + text[1:]


class SherpaTranscriber:
    def __init__(
        self,
        model_dir: str | Path | None = None,
        num_threads: int | None = None,
        decoding_method: str = "modified_beam_search",  # hoặc "greedy_search" (nhanh hơn chút)
    ):
        import sherpa_onnx

        d = Path(model_dir or DEFAULT_MODELS_DIR / DEFAULT_SHERPA_MODEL)
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=_pick(d, "encoder"),
            decoder=_pick(d, "decoder"),
            joiner=_pick(d, "joiner"),
            tokens=str(d / "tokens.txt"),
            num_threads=num_threads or max(1, (os.cpu_count() or 2) // 2),
            sample_rate=SAMPLE_RATE,
            decoding_method=decoding_method,
            max_active_paths=4,
        )

    def transcribe(self, chunk: AudioChunk) -> Utterance:
        return self.transcribe_many([chunk])[0]

    def transcribe_many(self, chunks: list[AudioChunk]) -> list[Utterance]:
        """Giải mã song song nhiều đoạn một lúc (nhanh hơn gọi từng đoạn)."""
        streams = []
        for c in chunks:
            s = self.recognizer.create_stream()
            s.accept_waveform(SAMPLE_RATE, c.audio)
            streams.append(s)
        self.recognizer.decode_streams(streams)
        return [self._to_utterance(c, s.result) for c, s in zip(chunks, streams)]

    @staticmethod
    def _to_utterance(chunk: AudioChunk, r) -> Utterance:
        # Gom token BPE thành từ: token bắt đầu bằng " " hoặc "▁" là đầu một từ mới.
        words: list[Word] = []
        for tok, ts in zip(r.tokens, r.timestamps):
            t = chunk.start + float(ts)
            if tok[:1] in (" ", "▁") or not words:
                if words:
                    words[-1].end = t
                words.append(Word(tok.lstrip(" ▁").lower(), t, t))
            else:
                words[-1].word += tok.lower()
        if words:
            words[-1].end = chunk.end
        words = [w for w in words if w.word]
        return Utterance(chunk.start, chunk.end, _normalize_vi(r.text), words)


class WhisperTranscriber:
    def __init__(
        self,
        model: str = "small",
        language: str | None = "vi",
        device: str = "cpu",
        compute_type: str = "int8",
        num_threads: int | None = None,
    ):
        from faster_whisper import WhisperModel

        local = DEFAULT_MODELS_DIR / f"faster-whisper-{model}"
        self.model = WhisperModel(
            str(local) if local.exists() else model,
            device=device,
            compute_type=compute_type,
            cpu_threads=num_threads or max(1, (os.cpu_count() or 2) // 2),
        )
        self.language = language

    def transcribe(self, chunk: AudioChunk) -> Utterance:
        segments, _ = self.model.transcribe(
            chunk.audio, language=self.language, word_timestamps=True, vad_filter=False, beam_size=1
        )
        words: list[Word] = []
        texts: list[str] = []
        for seg in segments:
            texts.append(seg.text.strip())
            for w in seg.words or []:
                words.append(Word(w.word.strip(), chunk.start + w.start, chunk.start + w.end))
        return Utterance(chunk.start, chunk.end, " ".join(texts).strip(), words)

    def transcribe_many(self, chunks: list[AudioChunk]) -> list[Utterance]:
        return [self.transcribe(c) for c in chunks]


def create_transcriber(backend: str = "sherpa", **kw) -> SherpaTranscriber | WhisperTranscriber:
    if backend == "sherpa":
        return SherpaTranscriber(
            kw.get("model_dir"), kw.get("num_threads"), kw.get("decoding_method", "modified_beam_search")
        )
    if backend == "whisper":
        return WhisperTranscriber(
            model=kw.get("whisper_model", "small"),
            language=kw.get("language", "vi"),
            device=kw.get("device", "cpu"),
            compute_type=kw.get("compute_type", "int8"),
            num_threads=kw.get("num_threads"),
        )
    raise ValueError(f"Backend không hỗ trợ: {backend}")
