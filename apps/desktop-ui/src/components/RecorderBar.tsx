// Thanh điều khiển thu âm: Bắt đầu/Dừng, chọn chế độ, đồng hồ, sóng âm.
import { useEffect, useRef, useState } from "react";
import { api } from "../services/apiClient";
import type { CaptureMode, Meeting, RecordingStatusData } from "../types";
import WaveformMeter, { type WaveformSample } from "./WaveformMeter";

interface Props {
  status: (RecordingStatusData & { meeting_id: string }) | null;
  waveform: WaveformSample | null;
  onSaved: () => void;
}

function defaultTitle(): string {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const mo = String(now.getMonth() + 1).padStart(2, "0");
  return `Cuộc họp ${dd}/${mo} ${hh}:${mm}`;
}

export default function RecorderBar({ status, waveform, onSaved }: Props) {
  const [title, setTitle] = useState(defaultTitle);
  const [mode, setMode] = useState<CaptureMode>("room");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meetingId, setMeetingId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [, setTick] = useState(0);

  const wsState = status?.state ?? null;
  const active = meetingId !== null || wsState === "recording" || wsState === "paused";
  const activeMeetingId = meetingId ?? status?.meeting_id ?? null;

  // Đồng hồ hiển thị: tự đếm local khi bắt đầu, dùng elapsed của WS khi có.
  const elapsedBase = useRef(0);
  const elapsedRef = useRef(0);
  useEffect(() => {
    if (status && status.state !== "stopped") {
      elapsedRef.current = status.elapsed_sec;
      if (!startedAt) setStartedAt(Date.now() - status.elapsed_sec * 1000);
    }
  }, [status, startedAt]);

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setTick((t) => t + 1), 500);
    return () => clearInterval(timer);
  }, [active]);

  const elapsed =
    wsState === "recording" || wsState === "paused"
      ? elapsedRef.current
      : startedAt
        ? Math.max(elapsedRef.current, (Date.now() - startedAt) / 1000)
        : elapsedBase.current;

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const meeting = await api.post<Meeting>("/recording/start", {
        title: title.trim() || defaultTitle(),
        capture_mode: mode,
      });
      setMeetingId(meeting.id);
      setStartedAt(Date.now());
      elapsedRef.current = 0;
      onSaved();
    } catch (e) {
      setError(`Không bắt đầu được ghi âm: ${(e as Error).message} — backend đã chạy chưa?`);
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!activeMeetingId) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/recording/${activeMeetingId}/stop`);
      elapsedBase.current = elapsed;
      setMeetingId(null);
      setStartedAt(null);
      onSaved();
    } catch (e) {
      setError(`Không dừng được ghi âm: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <footer className="recorder-bar">
      <div className="recorder-controls">
        <input
          className="title-input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          disabled={active}
          aria-label="Tên cuộc họp"
        />
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as CaptureMode)}
          disabled={active}
          aria-label="Chế độ ghi"
        >
          <option value="room">Phòng họp (mic + loa)</option>
          <option value="headset">Tai nghe</option>
        </select>
        <button
          className={`record-btn ${active ? "recording" : ""}`}
          onClick={active ? stop : start}
          disabled={busy}
        >
          {busy ? "Đang xử lý…" : active ? "■ Dừng ghi" : "● Bắt đầu ghi"}
        </button>
        <span className="timer">{formatClock(elapsed)}</span>
      </div>
      <WaveformMeter active={active} waveform={waveform} />
      {error && <div className="recorder-error">{error}</div>}
    </footer>
  );
}

function formatClock(totalSec: number): string {
  const s = Math.max(0, Math.floor(totalSec));
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
