"""Khôi phục dấu câu + viết hoa cho văn bản tiếng Việt (sau bước STT).

Model: ViBERT-capu (dragonSwing/vibert-capu) bản ONNX int8 của welcomyou/vibert-capu-onnx,
license CC-BY-SA-4.0. Kiểu GECToR "seq2labels": với mỗi từ, model dự đoán 1 thao tác
(giữ nguyên / thêm , . ? : sau từ / viết hoa / nối từ...). Chạy lặp vài vòng tới khi ổn định.

Chỉ cần onnxruntime + tokenizers (không cần PyTorch / transformers).

    >>> p = Punctuator()
    >>> p("hôm nay anh nam phụ trách kiểm thử hạn chót là thứ sáu")
    'Hôm nay anh Nam phụ trách kiểm thử, hạn chót là thứ sáu.'
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "models" / "vibert-capu-onnx"

START = "$START"
LABELS = [
    "$KEEP",
    "$TRANSFORM_CASE_CAPITAL",
    "$APPEND_,",
    "$APPEND_.",
    "$TRANSFORM_VERB_VB_VBN",
    "$TRANSFORM_CASE_UPPER",
    "$APPEND_:",
    "$APPEND_?",
    "$TRANSFORM_VERB_VB_VBC",
    "$TRANSFORM_CASE_LOWER",
    "$TRANSFORM_CASE_CAPITAL_1",
    "$TRANSFORM_CASE_UPPER_-1",
    "$MERGE_SPACE",
    "@@UNKNOWN@@",
    "@@PADDING@@",
]
PUNCT = {",", ".", "?", ":"}
_SKIP = {"$KEEP", "@@UNKNOWN@@", "@@PADDING@@", "$TRANSFORM_VERB_VB_VBN", "$TRANSFORM_VERB_VB_VBC"}


def _transform_case(tok: str, label: str) -> str:
    if not tok:
        return tok
    kind = label.removeprefix("$TRANSFORM_CASE_")
    return {
        "LOWER": tok.lower(),
        "UPPER": tok.upper(),
        "CAPITAL": tok[:1].upper() + tok[1:],
        "CAPITAL_1": tok[:1] + tok[1:2].upper() + tok[2:],
        "UPPER_-1": tok[:-1].upper() + tok[-1:],
    }.get(kind, tok)


def _apply(tokens: list[str], labels: list[str]) -> list[str]:
    """labels[0] ứng với $START, labels[i] ứng với tokens[i-1]."""
    out: list[str] = []
    merge_next = False
    for i, tok in enumerate(tokens, start=1):
        label = labels[i] if i < len(labels) else "$KEEP"
        if label.startswith("$TRANSFORM_CASE_"):
            tok = _transform_case(tok, label)
        if merge_next and out:
            out[-1] += tok
        else:
            out.append(tok)
        merge_next = False
        if label.startswith("$APPEND_"):
            p = label.removeprefix("$APPEND_")
            nxt = tokens[i] if i < len(tokens) else None
            if out[-1] != p and nxt != p:  # tránh thêm trùng dấu
                out.append(p)
        elif label == "$MERGE_SPACE":
            merge_next = True
    # Bỏ dấu câu lặp liên tiếp (", ." -> ",")
    cleaned: list[str] = []
    for t in out:
        if t in PUNCT and cleaned and cleaned[-1] in PUNCT:
            continue
        cleaned.append(t)
    return cleaned


class Punctuator:
    def __init__(
        self,
        model_dir: str | Path | None = None,
        max_words: int = 60,
        iterations: int = 3,
        num_threads: int | None = None,
    ):
        import onnxruntime as ort
        from tokenizers import Tokenizer, models, pre_tokenizers

        d = Path(model_dir or DEFAULT_DIR)
        onnx_path = next(iter(sorted(d.glob("*.int8.onnx"))), None) or next(iter(sorted(d.glob("*.onnx"))), None)
        if onnx_path is None or not (d / "vocab.txt").exists():
            raise FileNotFoundError(f"Thiếu model dấu câu trong {d}. Chạy scripts/download_models.py")

        vocab: dict[str, int] = {}
        with open(d / "vocab.txt", encoding="utf-8") as f:
            for i, line in enumerate(f):
                vocab[line.rstrip("\n")] = i
        vocab[START] = len(vocab)  # special_tokens_fix: $START được thêm vào cuối vocab
        tok = Tokenizer(models.WordPiece(vocab, unk_token="[UNK]", continuing_subword_prefix="##"))
        tok.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
        self.tok = tok

        so = ort.SessionOptions()
        so.intra_op_num_threads = num_threads or max(1, (os.cpu_count() or 2) // 2)
        self.sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
        self.max_words = max_words
        self.iterations = iterations

    # ---- suy luận 1 lô các câu (mỗi câu là list từ) ----
    def _predict(self, batch: list[list[str]]) -> list[list[str]]:
        encs = [self.tok.encode([START] + words, is_pretokenized=True) for words in batch]
        seq_len = max(len(e.ids) for e in encs)
        n_words = max(len(w) + 1 for w in batch)
        B = len(batch)
        ids = np.zeros((B, seq_len), np.int64)
        mask = np.zeros((B, seq_len), np.int64)
        offsets = np.zeros((B, n_words), np.int64)
        for b, e in enumerate(encs):
            ids[b, : len(e.ids)] = e.ids
            mask[b, : len(e.ids)] = 1
            firsts, prev = [], None
            for i, w in enumerate(e.word_ids):
                if w is not None and w != prev:
                    firsts.append(i)
                prev = w
            offsets[b, : len(firsts)] = firsts
        logits, _ = self.sess.run(
            None,
            {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids), "input_offsets": offsets},
        )
        preds = logits.argmax(-1)
        return [[LABELS[j] for j in preds[b, : len(batch[b]) + 1]] for b in range(B)]

    def _run(self, batch: list[list[str]]) -> list[list[str]]:
        cur = [list(w) for w in batch]
        active = list(range(len(cur)))
        for _ in range(self.iterations):
            if not active:
                break
            labels = self._predict([cur[i] for i in active])
            still = []
            for i, lab in zip(active, labels):
                if all(l in _SKIP for l in lab):
                    continue
                new = _apply(cur[i], lab)
                if new != cur[i]:
                    cur[i] = new
                    still.append(i)
            active = still
        return cur

    def punctuate_many(self, texts: list[str]) -> list[str]:
        # Cắt câu dài thành các khúc <= max_words từ (model huấn luyện với max_len=64).
        pieces: list[list[str]] = []
        owners: list[int] = []
        for idx, t in enumerate(texts):
            words = t.lower().split()
            for k in range(0, len(words), self.max_words):
                pieces.append(words[k : k + self.max_words])
                owners.append(idx)
        results = self._run(pieces) if pieces else []

        joined: list[list[str]] = [[] for _ in texts]
        for owner, toks in zip(owners, results):
            joined[owner] += toks
        out = []
        for toks in joined:
            s = re.sub(r"\s+([,.?:])", r"\1", " ".join(toks)).strip()
            if s:
                s = s[0].upper() + s[1:]
                if s[-1] not in ".?":
                    s = s.rstrip(",:") + "."
            out.append(s)
        return out

    def __call__(self, text: str) -> str:
        return self.punctuate_many([text])[0]
