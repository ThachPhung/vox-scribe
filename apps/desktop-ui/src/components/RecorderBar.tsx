// Thanh ghi âm nổi ở cuối màn hình khi đang ghi mà người dùng mở màn hình khác.
import type { Recorder } from "../hooks/useRecorder";
import { formatClock } from "../hooks/useRecorder";
import Icon from "./Icon";
import WaveformMeter, { type WaveformSample } from "./WaveformMeter";

interface Props {
  recorder: Recorder;
  waveform: WaveformSample | null;
  onOpen: () => void;
}

export default function RecorderBar({ recorder, waveform, onOpen }: Props) {
  if (!recorder.active) return null;
  return (
    <div className="dock" role="region" aria-label="Đang ghi âm">
      <button className="dock-info" onClick={onOpen} title="Mở màn hình ghi âm">
        <span className="rec-dot" />
        <span className="dock-clock">{formatClock(recorder.elapsed)}</span>
      </button>
      <WaveformMeter active waveform={waveform} bars={28} className="waveform-sm" />
      <button
        className="dock-stop"
        onClick={recorder.stop}
        disabled={recorder.busy}
        title="Dừng và lưu"
        aria-label="Dừng và lưu"
      >
        <Icon name="stop" size={14} />
      </button>
      {recorder.error && <span className="dock-error">{recorder.error}</span>}
    </div>
  );
}
