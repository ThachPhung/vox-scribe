// Màn hình chi tiết một cuộc họp: lời thoại bên trái, biên bản bên phải.
// Cửa sổ hẹp thì chuyển sang hai tab.
import { useEffect, useState } from "react";
import { api } from "../services/apiClient";
import type { Meeting, Transcript } from "../types";
import { fmtDateTime, fmtDuration } from "../utils";
import CopyButton from "./CopyButton";
import Icon from "./Icon";
import ReportEditor from "./ReportEditor";
import TranscriptView, { transcriptToText } from "./TranscriptView";

interface Props {
  meetingId: string;
}

type Tab = "transcript" | "report";

export default function MeetingDetail({ meetingId }: Props) {
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
    <section className="detail">
      <header className="detail-head">
        <div className="detail-title">
          <h1>{meeting?.title ?? "…"}</h1>
          {meeting && (
            <div className="meta-row">
              <span>
                <Icon name="calendar" size={14} /> {fmtDateTime(meeting.started_at)}
              </span>
              <span>
                <Icon name="clock" size={14} /> {fmtDuration(meeting.duration_sec)}
              </span>
              <span>
                <Icon name={meeting.capture_mode === "headset" ? "headset" : "room"} size={14} />
                {meeting.capture_mode === "headset" ? "Tai nghe" : "Phòng họp"}
              </span>
              {meeting.status === "recording" && (
                <span className="chip danger">
                  <span className="rec-dot" /> Đang ghi
                </span>
              )}
            </div>
          )}
        </div>

        <div className="segmented" role="tablist" aria-label="Nội dung cuộc họp">
          <button role="tab" aria-selected={tab === "transcript"} onClick={() => setTab("transcript")}>
            Lời thoại
          </button>
          <button role="tab" aria-selected={tab === "report"} onClick={() => setTab("report")}>
            Biên bản
          </button>
        </div>
      </header>

      <div className={`detail-body show-${tab}`}>
        <div className="pane pane-transcript">
          <div className="pane-head">
            <h2>Lời thoại</h2>
            {transcript && <span className="chip">{transcript.segments.length} câu</span>}
            <div className="pane-actions">
              {transcript && transcript.segments.length > 0 && (
                <CopyButton getText={() => transcriptToText(transcript.segments)} />
              )}
            </div>
          </div>
          <div className="pane-body">
            {transcriptError ? (
              <div className="empty-state">
                <div className="empty-icon">
                  <Icon name="wave" size={22} />
                </div>
                <h3>Chưa có lời thoại</h3>
                <p>{transcriptError}</p>
              </div>
            ) : transcript ? (
              <TranscriptView segments={transcript.segments} />
            ) : (
              <p className="pane-empty">Đang tải…</p>
            )}
          </div>
        </div>

        <div className="pane-report">
          <ReportEditor meetingId={meetingId} />
        </div>
      </div>
    </section>
  );
}
