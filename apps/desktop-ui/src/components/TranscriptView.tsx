// Hiển thị lời thoại theo câu, gộp câu liên tiếp của cùng người nói.
// Bấm câu để đánh dấu (mốc tua tới WAV gốc).
import { useMemo, useState } from "react";
import type { Segment } from "../types";
import { fmtDuration } from "../utils";
import Icon from "./Icon";

interface Props {
  segments: Segment[];
}

const PALETTE_SIZE = 6;

export default function TranscriptView({ segments }: Props) {
  const [selected, setSelected] = useState<number | null>(null);

  // Màu theo thứ tự xuất hiện của nhãn người nói, ổn định trong một cuộc họp.
  const colorOf = useMemo(() => {
    const order = new Map<string, number>();
    for (const s of segments) {
      if (!order.has(s.speaker_label)) order.set(s.speaker_label, order.size);
    }
    return (label: string) => `var(--spk-${(order.get(label) ?? 0) % PALETTE_SIZE})`;
  }, [segments]);

  if (segments.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon">
          <Icon name="wave" size={22} />
        </div>
        <h3>Chưa có lời thoại</h3>
        <p>Lời thoại theo từng người nói sẽ hiện ở đây sau khi bản ghi được chép lời.</p>
      </div>
    );
  }

  return (
    <ol className="transcript">
      {segments.map((seg, i) => {
        const sameSpeaker = i > 0 && segments[i - 1].speaker_label === seg.speaker_label;
        const unknown = seg.speaker_name == null;
        return (
          <li
            key={seg.id}
            className={`${seg.id === selected ? "selected" : ""} ${sameSpeaker ? "cont" : ""}`}
            onClick={() => setSelected(seg.id)}
          >
            <span className="ts">{fmtDuration(seg.start_sec)}</span>
            <div className="seg-body">
              {!sameSpeaker && (
                <span className={`speaker ${unknown ? "unknown" : ""}`} style={{ color: colorOf(seg.speaker_label) }}>
                  <i style={{ background: colorOf(seg.speaker_label) }} />
                  {seg.speaker_name ?? `Chưa rõ (${seg.speaker_label})`}
                </span>
              )}
              <p>{seg.text}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Ghép transcript thành văn bản thuần để sao chép. */
export function transcriptToText(segments: Segment[]): string {
  return segments
    .map((s) => `[${fmtDuration(s.start_sec)}] ${s.speaker_name ?? s.speaker_label}: ${s.text}`)
    .join("\n");
}
