// Màn hình chính: chuẩn bị ghi cuộc họp mới, hoặc theo dõi buổi đang ghi.
import type { Recorder } from "../hooks/useRecorder";
import { formatClock } from "../hooks/useRecorder";
import type { CaptureMode } from "../types";
import Icon, { type IconName } from "./Icon";
import WaveformMeter, { isWaveformFresh, type WaveformSample } from "./WaveformMeter";

interface Props {
  recorder: Recorder;
  waveform: WaveformSample | null;
  connected: boolean;
  /** Tên thật của cuộc họp đang ghi (lấy từ danh sách), đúng cả khi tải lại trang giữa chừng. */
  liveTitle?: string;
}

/** Đợi vài giây đầu trước khi báo thiếu dữ liệu sóng âm, tránh chữ nháy lúc mới bắt đầu. */
const NO_LEVEL_GRACE_SEC = 2;

const MODES:{ value: CaptureMode; icon: IconName; label: string; hint: string }[] = [
  { value: "room", icon: "room", label: "Phòng họp", hint: "Mic + loa, họp trực tiếp" },
  { value: "headset", icon: "headset", label: "Tai nghe", hint: "Họp online qua Meet, Zoom, Teams" },
];

export default function HomeView({ recorder, waveform, connected, liveTitle }: Props) {
  const { active, busy, error } = recorder;

  if (active) {
    return (
      <section className="home">
        <div className="live-card">
          <div className="live-head">
            <span className="live-pill">
              <span className="rec-dot" /> Đang ghi
            </span>
            <span className="live-title">{liveTitle ?? recorder.title}</span>
          </div>
          <div className="live-clock">{formatClock(recorder.elapsed)}</div>
          <WaveformMeter active waveform={waveform} bars={120} className="waveform-lg" />
          <div className="wave-legend">
            <span>
              <i className="swatch mic" /> Mic (kênh trái)
            </span>
            <span>
              <i className="swatch sys" /> Âm thanh hệ thống (kênh phải)
            </span>
            {!isWaveformFresh(waveform) && recorder.elapsed > NO_LEVEL_GRACE_SEC && (
              <span className="muted">Chưa nhận được mức âm từ backend</span>
            )}
          </div>
          <button className="btn btn-stop" onClick={recorder.stop} disabled={busy}>
            <Icon name="stop" size={14} />
            {busy ? "Đang dừng…" : "Dừng và lưu"}
          </button>
          {error && <p className="form-error">{error}</p>}
        </div>
        <p className="home-foot">Bạn có thể mở cuộc họp khác trong lúc ghi. Thanh ghi âm sẽ nổi ở cuối màn hình.</p>
      </section>
    );
  }

  return (
    <section className="home">
      <header className="home-head">
        <h1>Ghi cuộc họp mới</h1>
        <p>Bản ghi lưu trên máy này. Kênh trái là mic, kênh phải là âm thanh hệ thống.</p>
      </header>

      <form
        className="start-card"
        onSubmit={(e) => {
          e.preventDefault();
          void recorder.start();
        }}
      >
        <label className="field">
          <span className="field-label">Tên cuộc họp</span>
          <input
            className="input"
            value={recorder.title}
            onChange={(e) => recorder.setTitle(e.target.value)}
            placeholder="Ví dụ: Giao ban tuần 46"
          />
        </label>

        <fieldset className="field">
          <legend className="field-label">Chế độ ghi</legend>
          <div className="mode-grid" role="radiogroup">
            {MODES.map((m) => (
              <button
                type="button"
                key={m.value}
                role="radio"
                aria-checked={recorder.mode === m.value}
                className={`mode-option ${recorder.mode === m.value ? "selected" : ""}`}
                onClick={() => recorder.setMode(m.value)}
              >
                <Icon name={m.icon} size={20} />
                <span>
                  <strong>{m.label}</strong>
                  <small>{m.hint}</small>
                </span>
              </button>
            ))}
          </div>
        </fieldset>

        <button type="submit" className="btn btn-record" disabled={busy}>
          <span className="rec-dot static" />
          {busy ? "Đang bắt đầu…" : "Bắt đầu ghi"}
        </button>
        {error && <p className="form-error">{error}</p>}
        {!connected && !error && (
          <p className="form-hint">
            <Icon name="alert" size={14} /> Chưa kết nối backend. Chạy <code>python main.py</code> trong{" "}
            <code>services/backend</code> trước khi ghi.
          </p>
        )}
      </form>
    </section>
  );
}
