// Khớp với shared/schemas + model pydantic của core_app (TV3).

export type CaptureMode = "headset" | "room";
export type MeetingStatus = "recording" | "recorded";

export interface Meeting {
  id: string;
  title: string;
  audio_path: string | null;
  started_at: string;
  duration_sec: number | null;
  capture_mode: CaptureMode | null;
  status: MeetingStatus;
  created_at: string;
}

export interface Word {
  word: string;
  start: number;
  end: number;
}

export interface Segment {
  id: number;
  start_sec: number;
  end_sec: number;
  speaker_label: string;
  speaker_name: string | null;
  text: string;
  words: Word[] | null;
}

export interface Transcript {
  meeting_id: string;
  revision: number;
  segments: Segment[];
}

export interface ReportItem {
  content: string;
  evidence_at: string;
}

export interface ActionItem {
  task: string;
  owner: string | null;
  deadline: string | null;
  evidence_at: string;
}

export interface MeetingReport {
  goals: ReportItem[];
  decisions: ReportItem[];
  open_issues: ReportItem[];
  action_items: ActionItem[];
}

export interface Report {
  meeting_id: string;
  transcript_revision: number;
  content: MeetingReport;
  warnings: string[];
  revision: number;
  stale: boolean;
  created_at: string;
  updated_at: string;
}

// Sự kiện WebSocket, khớp core_app/api/websocket.py.
export interface RecordingStatusData {
  state: "recording" | "paused" | "stopped";
  elapsed_sec: number;
}

export type WsEvent =
  | { type: "recording.status"; meeting_id: string; data: RecordingStatusData }
  | { type: "recording.waveform"; meeting_id: string; data: { left: number; right: number } }
  | { type: "network.status"; meeting_id: null; data: { online: boolean } }
  | { type: "app.detected"; meeting_id: null; data: { app: "zoom" | "teams" | "meet" } }
  | { type: "job.progress"; meeting_id: string; data: unknown }
  | { type: "job.error"; meeting_id: string; data: unknown };
