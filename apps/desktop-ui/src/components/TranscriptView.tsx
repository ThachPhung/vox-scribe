// Hiển thị lời thoại theo câu, bấm câu để đánh dấu (mốc tua tới WAV).
import { useState } from "react";
import type { Segment } from "../types";
import { fmtDuration } from "../utils";

interface Props {
  segments: Segment[];
}

export default function TranscriptView({ segments }: Props) {
  const [selected, setSelected] = useState<number | null>(null);

  if (segments.length === 0) {
    return <p className="empty">Chưa có lời thoại cho cuộc họp này.</p>;
  }

  return (
    <ul className="transcript">
      {segments.map((seg) => (
        <li
          key={seg.id}
          className={seg.id === selected ? "selected" : ""}
          onClick={() => setSelected(seg.id)}
        >
          <span className="ts">[{fmtDuration(seg.start_sec)}]</span>
          <span className="speaker">{seg.speaker_name ?? seg.speaker_label}</span>
          <span className="text">{seg.text}</span>
        </li>
      ))}
    </ul>
  );
}
