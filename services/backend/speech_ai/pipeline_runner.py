"""Điều phối toàn bộ luồng từ file .wav ra JSON lời thoại.

File stereo của audio_engine (Trái = Mic, Phải = Loa/Zoom/Meet/Teams):

    Kênh Trái (Mic) ─► Silero VAD ─► SPEAKER_00 (người dùng máy này)
                         └─ bỏ đoạn "vọng" từ loa vào mic (echo/bleed)
    Kênh Phải (Loa) ─► diarization (pyannote-seg-3.0 + CAM++ + refine) ─► SPEAKER_01, 02...
    các đoạn ─► STT (Zipformer-vi int8 | faster-whisper) ─► dấu câu (ViBERT-capu)
    mỗi SPEAKER_xx ─► vector CAM++ 192 chiều ─► so khớp danh bạ giọng ─► speaker_name

File mono: cả file đi theo nhánh Kênh Phải (SPEAKER_01, 02...).

Đầu ra theo shared/schemas/transcript_contract.json.

Chạy thử (từ thư mục services/backend):
    python -m speech_ai.pipeline_runner samples/meeting.wav -o out.json
    python -m speech_ai.pipeline_runner meeting_stereo.wav --voicebook data/voicebook.json --mic-name "Thạch"
    # Dùng chung DB với core_app: so khớp từ voice_profiles + tự học sample mới
    python -m speech_ai.pipeline_runner meeting_stereo.wav --db data/voxscribe.db --meeting-id <id> --mic-name "Thạch"
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .audio_chunker import SAMPLE_RATE, AudioChunk, VadSegmenter, load_audio, probe_channels, split_fixed
from .diarizer import Diarizer, DiarizerConfig
from .embedder import Embedder
from .punctuator import Punctuator
from .speaker_matcher import DEFAULT_THRESHOLD, JsonVoiceBook, SpeakerMatcher
from .transcriber import DEFAULT_MODELS_DIR, Utterance, create_transcriber

UNKNOWN = "SPEAKER_UNKNOWN"
MIC_LABEL = "SPEAKER_00"
DEFAULT_VAD = DEFAULT_MODELS_DIR / "silero_vad.onnx"


@dataclass
class PipelineConfig:
    backend: str = "sherpa"  # sherpa | whisper
    whisper_model: str = "small"
    language: str | None = "vi"
    diarize: bool = True
    num_speakers: int | None = None  # số người ở Kênh Phải (hoặc cả file mono)
    cluster_threshold: float = 0.5
    merge_threshold: float = 0.65
    max_segment_sec: float = 20.0
    batch_size: int = 16
    num_threads: int | None = None
    include_words: bool = False
    punctuate: bool = True  # backend whisper đã có dấu câu sẵn -> bỏ qua
    voicebook: str | None = None  # đường dẫn danh bạ giọng (JSON); None = không so khớp tên
    match_threshold: float = DEFAULT_THRESHOLD
    mic_name: str | None = None  # tên người dùng Mic (nếu biết), ưu tiên hơn so khớp danh bạ
    drop_bleed: bool = True
    db_path: str | None = None  # DB SQLite của core_app; có thì dùng thay voicebook JSON
    learn: bool = True  # tự học sample vào DB (chỉ khi có db_path)
    learning_policy: "LearningPolicy | None" = None


@dataclass
class PipelineResult:
    transcript: dict
    timings: dict[str, float] = field(default_factory=dict)
    learning: list = field(default_factory=list)  # list[LearnEvent]


@dataclass
class _Speaker:
    label: str
    channel: str  # "mic" | "system" | "mono"
    spans: list[tuple[float, float]] = field(default_factory=list)
    embedding: np.ndarray | None = None
    duration: float = 0.0
    audio: np.ndarray | None = None  # kênh chứa giọng người này (để tạo sample tự học)


# ------------------------------------------------------------------ helpers
def _frame_rms(x: np.ndarray, frame: int = 320) -> np.ndarray:  # 20ms
    n = len(x) // frame
    return np.sqrt((x[: n * frame].reshape(n, frame) ** 2).mean(1) + 1e-10) if n else np.zeros(0)


def _is_bleed(mic: np.ndarray, sys: np.ndarray) -> bool:
    """Đoạn mic chỉ là tiếng loa vọng vào? (không đeo tai nghe)

    Dấu hiệu: đường bao năng lượng (20ms) của mic gần như trùng với kênh loa
    và kênh loa to hơn hẳn. Người dùng nói thật thì đường bao mic khác loa.
    """
    em, es = _frame_rms(mic), _frame_rms(sys)
    if len(em) < 10 or es.mean() < 1e-3:
        return False
    lm, ls = np.log(em), np.log(es)
    if lm.std() < 1e-6 or ls.std() < 1e-6:
        return False
    corr = float(np.corrcoef(lm, ls)[0, 1])
    return corr > 0.8 and es.mean() > 1.5 * em.mean()


def _split_long(audio: np.ndarray, start: float, end: float, vad: VadSegmenter, max_sec: float) -> list[AudioChunk]:
    piece = audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
    if len(piece) == 0:
        return []
    if end - start <= max_sec:
        return [AudioChunk(start, piece)]
    return vad.segment(piece, offset=start) or split_fixed(piece, start, max_sec)


def _system_branch(
    audio: np.ndarray, cfg: PipelineConfig, vad: VadSegmenter, embedder: Embedder, channel: str, timings: dict
) -> tuple[list[tuple[str, AudioChunk]], dict[str, _Speaker]]:
    if not cfg.diarize:
        return [(UNKNOWN, c) for c in vad.segment(audio)], {}
    t = time.perf_counter()
    res = Diarizer(
        DiarizerConfig(
            num_speakers=cfg.num_speakers,
            threshold=cfg.cluster_threshold,
            merge_threshold=cfg.merge_threshold,
            num_threads=cfg.num_threads,
            label_offset=1,
        ),
        embedder=embedder,
    ).diarize(audio)
    timings["diarize"] = round(time.perf_counter() - t, 2)

    chunks, speakers = [], {}
    for turn in res.turns:
        sp = speakers.setdefault(turn.speaker, _Speaker(turn.speaker, channel, audio=audio))
        sp.spans.append((turn.start, turn.end))
        chunks += [(turn.speaker, c) for c in _split_long(audio, turn.start, turn.end, vad, cfg.max_segment_sec)]
    for lab, sp in speakers.items():
        sp.embedding = res.centroids.get(lab)
        sp.duration = res.durations.get(lab, 0.0)
    return chunks, speakers


def _mic_branch(
    mic: np.ndarray, sys: np.ndarray, cfg: PipelineConfig, vad: VadSegmenter, embedder: Embedder, timings: dict
) -> tuple[list[tuple[str, AudioChunk]], dict[str, _Speaker]]:
    t = time.perf_counter()
    chunks, dropped = [], 0
    for c in vad.segment(mic):
        a, b = int(c.start * SAMPLE_RATE), int(c.end * SAMPLE_RATE)
        if cfg.drop_bleed and _is_bleed(c.audio, sys[a:b]):
            dropped += 1
            continue
        chunks.append((MIC_LABEL, c))
    sp = _Speaker(MIC_LABEL, "mic", [(c.start, c.end) for _, c in chunks], audio=mic)
    sp.embedding, sp.duration = embedder.embed_segments(mic, sp.spans)
    timings["mic_vad"] = round(time.perf_counter() - t, 2)
    timings["mic_bleed_dropped"] = dropped
    return chunks, ({MIC_LABEL: sp} if chunks else {})


def _identify(speakers: dict[str, _Speaker], cfg: PipelineConfig, embedder: Embedder, book=None) -> dict[str, dict]:
    """Gán tên thật cho từng SPEAKER_xx (Mic dùng --mic-name nếu có)."""
    info = {
        lab: {"speaker_id": None, "name": None, "score": None}
        for lab in speakers
    }
    if cfg.mic_name and MIC_LABEL in info:
        info[MIC_LABEL]["name"] = cfg.mic_name
    if book is None and cfg.voicebook:
        book = JsonVoiceBook(cfg.voicebook)
    if book is not None:
        matcher = SpeakerMatcher(book, embedder.model_name, cfg.match_threshold)
        cents = {
            lab: sp.embedding
            for lab, sp in speakers.items()
            if sp.embedding is not None and not (lab == MIC_LABEL and cfg.mic_name)
        }
        for lab, m in matcher.match_clusters(cents).items():
            info[lab] = {"speaker_id": m.speaker_id, "name": m.name, "score": m.score}
    return info


def _learn(meeting_id: str, speakers: dict[str, _Speaker], info: dict[str, dict], cfg: PipelineConfig, embedder: Embedder, book) -> list:
    from .voice_learning import Candidate, LearningPolicy, VoiceLearner, make_samples

    policy = cfg.learning_policy or LearningPolicy()
    cands = []
    for lab, sp in speakers.items():
        if sp.embedding is None or sp.audio is None:
            continue
        hint = cfg.mic_name if lab == MIC_LABEL else None
        sid = info[lab]["speaker_id"] if not hint else None
        if sid is None and hint is None:
            continue  # người lạ: không biết tên -> chờ /speakers/confirm
        samples = make_samples(embedder, sp.audio, sp.spans, policy.sample_sec) if sp.duration >= policy.min_speech_sec else []
        cands.append(Candidate(lab, sp.embedding, sp.duration, samples, sid, hint))
    return VoiceLearner(book, embedder.model_name, policy).learn(meeting_id, cands)


def _to_contract(
    meeting_id: str,
    language: str | None,
    items: list[tuple[str, Utterance]],
    speakers: dict[str, _Speaker],
    info: dict[str, dict],
    embedding_model: str,
    words: bool,
) -> dict:
    segments = []
    for label, u in sorted(items, key=lambda x: x[1].start):
        if not u.text:
            continue
        seg = {
            "start": round(u.start, 3),
            "end": round(u.end, 3),
            "speaker_label": label,
            "speaker_name": info.get(label, {}).get("name"),
            "text": u.text,
        }
        if words:
            seg["words"] = [{k: round(v, 3) if isinstance(v, float) else v for k, v in asdict(w).items()} for w in u.words]
        segments.append(seg)
    spk_out = [
        {
            "label": lab,
            "channel": sp.channel,
            "speaker_id": info[lab]["speaker_id"],
            "name": info[lab]["name"],
            "match_score": info[lab]["score"],
            "duration_sec": round(sp.duration, 2),
            "embedding_model": embedding_model,
            # Vector để UI/core_app enroll người lạ (SpeakerTagModal) mà không phải tính lại
            "embedding": None if sp.embedding is None else [round(float(x), 6) for x in sp.embedding],
        }
        for lab, sp in sorted(speakers.items())
    ]
    return {"meeting_id": meeting_id, "language": language, "speakers": spk_out, "segments": segments}


# ------------------------------------------------------------------ main entry
def run_pipeline(
    audio_path: str,
    meeting_id: str | None = None,
    channel: str = "auto",  # auto | stereo | mix | left | right
    cfg: PipelineConfig | None = None,
) -> PipelineResult:
    cfg = cfg or PipelineConfig()
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    if channel == "auto":
        channel = "stereo" if probe_channels(audio_path) >= 2 else "mix"
    timings["mode"] = channel  # type: ignore[assignment]

    vad = VadSegmenter(str(DEFAULT_VAD), max_speech_sec=cfg.max_segment_sec)
    embedder = Embedder(num_threads=cfg.num_threads)

    if channel == "stereo":
        mic, sys = load_audio(audio_path, "left"), load_audio(audio_path, "right")
        timings["audio_sec"] = round(len(sys) / SAMPLE_RATE, 2)
        chunks, speakers = _system_branch(sys, cfg, vad, embedder, "system", timings)
        mic_chunks, mic_spk = _mic_branch(mic, sys, cfg, vad, embedder, timings)
        chunks += mic_chunks
        speakers.update(mic_spk)
    else:
        audio = load_audio(audio_path, channel=channel)  # type: ignore[arg-type]
        timings["audio_sec"] = round(len(audio) / SAMPLE_RATE, 2)
        chunks, speakers = _system_branch(audio, cfg, vad, embedder, "mono", timings)

    t = time.perf_counter()
    stt = create_transcriber(
        cfg.backend, whisper_model=cfg.whisper_model, language=cfg.language, num_threads=cfg.num_threads
    )
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

    t = time.perf_counter()
    meeting_id = meeting_id or Path(audio_path).stem
    book, learning = None, []
    if cfg.db_path:
        from .voice_learning import SqliteVoiceBook

        book = SqliteVoiceBook.open(cfg.db_path)
    try:
        info = _identify(speakers, cfg, embedder, book)
        timings["identify"] = round(time.perf_counter() - t, 2)
        if book is not None and cfg.learn:
            t = time.perf_counter()
            learning = _learn(meeting_id, speakers, info, cfg, embedder, book)
            timings["learn"] = round(time.perf_counter() - t, 2)
    finally:
        if book is not None:
            book.close()

    timings["total"] = round(time.perf_counter() - t0, 2)
    timings["rtf"] = round(timings["total"] / max(timings["audio_sec"], 1e-6), 3)  # < 1 là nhanh hơn thời gian thực
    transcript = _to_contract(meeting_id, cfg.language, items, speakers, info, embedder.model_name, cfg.include_words)
    return PipelineResult(transcript, timings, learning)


def main() -> None:
    p = argparse.ArgumentParser(description="VoxScribe speech pipeline (sherpa-onnx / faster-whisper)")
    p.add_argument("audio")
    p.add_argument("-o", "--out", help="File JSON đầu ra (mặc định in ra màn hình)")
    p.add_argument("--meeting-id")
    p.add_argument(
        "--channel", choices=["auto", "stereo", "mix", "left", "right"], default="auto",
        help="auto: file 2 kênh -> stereo (Trái=Mic, Phải=Loa), 1 kênh -> mix",
    )
    p.add_argument("--backend", choices=["sherpa", "whisper"], default="sherpa")
    p.add_argument("--whisper-model", default="small", help="tiny/base/small/medium/large-v3-turbo")
    p.add_argument("--language", default="vi")
    p.add_argument("--no-diarize", action="store_true")
    p.add_argument("--num-speakers", type=int, help="Số người ở Kênh Phải / file mono, nếu biết trước")
    p.add_argument("--threshold", type=float, default=0.5, help="Ngưỡng FastClustering (tầng 1)")
    p.add_argument("--merge-threshold", type=float, default=0.65, help="Cosine để gộp 2 cụm thành 1 người")
    p.add_argument("--max-segment", type=float, default=20.0, help="Độ dài tối đa 1 đoạn đưa vào STT (giây)")
    p.add_argument("--threads", type=int)
    p.add_argument("--words", action="store_true", help="Kèm timestamp từng từ trong JSON")
    p.add_argument("--no-punct", action="store_true", help="Không thêm dấu câu / viết hoa")
    p.add_argument("--voicebook", help="Danh bạ giọng (JSON) để gán tên thật, vd data/voicebook.json")
    p.add_argument("--match-threshold", type=float, default=DEFAULT_THRESHOLD)
    p.add_argument("--mic-name", help="Tên người dùng Mic (Kênh Trái)")
    p.add_argument("--keep-bleed", action="store_true", help="Không lọc tiếng loa vọng vào mic")
    p.add_argument("--db", help="DB SQLite của core_app (so khớp + tự học); thay cho --voicebook")
    p.add_argument("--no-learn", action="store_true", help="Có --db nhưng không ghi sample tự học")
    p.add_argument("--min-learn-sec", type=float, default=30.0, help="Ngưỡng sàn số giây nói để được tự học")
    p.add_argument("--max-learn-samples", type=int, default=2, help="Số sample tự học tối đa / người / cuộc họp")
    a = p.parse_args()

    cfg = PipelineConfig(
        backend=a.backend,
        whisper_model=a.whisper_model,
        language=a.language,
        diarize=not a.no_diarize,
        num_speakers=a.num_speakers,
        cluster_threshold=a.threshold,
        merge_threshold=a.merge_threshold,
        max_segment_sec=a.max_segment,
        num_threads=a.threads,
        include_words=a.words,
        punctuate=not a.no_punct,
        voicebook=a.voicebook,
        match_threshold=a.match_threshold,
        mic_name=a.mic_name,
        drop_bleed=not a.keep_bleed,
        db_path=a.db,
        learn=not a.no_learn,
    )
    if a.db:
        from .voice_learning import LearningPolicy

        cfg.learning_policy = LearningPolicy(min_speech_sec=a.min_learn_sec, max_samples_per_meeting=a.max_learn_samples)
    res = run_pipeline(a.audio, a.meeting_id, a.channel, cfg)

    text = json.dumps(res.transcript, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"Đã ghi {a.out}")
    else:
        print(text)
    print("Thời gian (giây):", res.timings)
    for ev in res.learning:
        print(f"Tự học {ev.label} ({ev.name or '?'}): {ev.action} - {ev.detail}")


if __name__ == "__main__":
    main()
