// Màn hình chi tiết một cuộc họp: Transcript + Biên bản.
import { useEffect, useState } from "react";
import { api } from "../services/apiClient";
import type { Meeting, Transcript } from "../types";
import { fmtDateTime, fmtDuration } from "../utils";
import ReportEditor from "./ReportEditor";
import TranscriptView from "./TranscriptView";

interface Props {
  meetingId: string;
  onBack: () => void;
}

type Tab = "transcript" | "report";

export default function MeetingDetail({ meetingId, onBack }: Props) {
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("transcript");

  useEffect(() => {
    setMeeting(null);
    setTranscript(null);
    setTranscriptError(null);
    api.get<Meeting>(`/meetings/${meetingId}`).then(setMeeting).catch(() => setMeeting(null));
    api
      .get<Transcript>(`/meetings/${meetingId}/transcript`)
      .then((t) => {
        setTranscript(t);
        setTranscriptError(null);
      })
      .catch((e: Error) => setTranscriptError(e.message));
  }, [meetingId]);

  return (
    <section className="meeting-detail">
      <div className="section-head">
        <button className="ghost" onClick={onBack}>
          ← Quay lại
        </button>
        <h2>{meeting?.title ?? "…"}</h2>
        {meeting && (
          <span className="detail-meta">
            {fmtDateTime(meeting.started_at)} · {fmtDuration(meeting.duration_sec)} ·{" "}
            {meeting.capture_mode === "headset" ? "Tai nghe" : "Phòng họp"}
          </span>
        )}
      </div>

      <nav className="tabs">
        <button className={tab === "transcript" ? "active" : ""} onClick={() => setTab("transcript")}>
          Lời thoại
        </button>
        <button className={tab === "report" ? "active" : ""} onClick={() => setTab("report")}>
          Biên bản
        </button>
      </nav>

      {tab === "transcript" &&
        (transcriptError ? (
          <p className="empty">Chưa có transcript: {transcriptError}</p>
        ) : transcript ? (
          <TranscriptView segments={transcript.segments} />
        ) : (
          <p className="empty">Đang tải…</p>
        ))}

      {tab === "report" && <ReportEditor meetingId={meetingId} />}
    </section>
  );
}
