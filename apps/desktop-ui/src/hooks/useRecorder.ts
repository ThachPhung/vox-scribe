// Trạng thái và thao tác ghi âm dùng chung cho màn hình chính và thanh nổi khi đang ghi.
import { useEffect, useRef, useState } from "react";
import { api } from "../services/apiClient";
import type { CaptureMode, Meeting, RecordingStatusData } from "../types";

export type LiveStatus = (RecordingStatusData & { meeting_id: string }) | null;

export function defaultTitle(): string {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const mo = String(now.getMonth() + 1).padStart(2, "0");
  return `Cuộc họp ${dd}/${mo} ${hh}:${mm}`;
}

export interface Recorder {
  title: string;
  setTitle: (v: string) => void;
  mode: CaptureMode;
  setMode: (v: CaptureMode) => void;
  busy: boolean;
  error: string | null;
  active: boolean;
  elapsed: number;
  meetingId: string | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

interface Options {
  /** Gọi sau khi bắt đầu ghi thành công. */
  onStarted: (meetingId: string) => void;
  /** Gọi sau khi dừng ghi thành công. */
  onStopped: (meetingId: string) => void;
}

export function useRecorder(status: LiveStatus, { onStarted, onStopped }: Options): Recorder {
  const [title, setTitle] = useState(defaultTitle);
  const [mode, setMode] = useState<CaptureMode>("room");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meetingId, setMeetingId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [, setTick] = useState(0);

  const wsState = status?.state ?? null;
  const active = meetingId !== null || wsState === "recording" || wsState === "paused";
  const activeMeetingId = meetingId ?? (active ? (status?.meeting_id ?? null) : null);

  // Đồng hồ: tự đếm local khi bắt đầu, dùng elapsed của WS khi có.
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
      onStarted(meeting.id);
    } catch (e) {
      setError(`Không bắt đầu được ghi âm: ${(e as Error).message}. Backend đã chạy chưa?`);
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!activeMeetingId) return;
    const id = activeMeetingId;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/recording/${id}/stop`);
      elapsedBase.current = elapsed;
      setMeetingId(null);
      setStartedAt(null);
      setTitle(defaultTitle());
      onStopped(id);
    } catch (e) {
      setError(`Không dừng được ghi âm: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return {
    title,
    setTitle,
    mode,
    setMode,
    busy,
    error,
    active,
    elapsed,
    meetingId: activeMeetingId,
    start,
    stop,
  };
}

export function formatClock(totalSec: number): string {
  const s = Math.max(0, Math.floor(totalSec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const mm = String(m).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}
