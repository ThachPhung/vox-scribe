import { useCallback, useState } from "react";
import MeetingDetail from "./components/MeetingDetail";
import MeetingsList from "./components/MeetingsList";
import RecorderBar from "./components/RecorderBar";
import { useAudioStream } from "./hooks/useAudioStream";
import { useMeetings } from "./hooks/useMeetings";
import type { WaveformSample } from "./components/WaveformMeter";
import type { RecordingStatusData, WsEvent } from "./types";

type View = { kind: "list" } | { kind: "detail"; meetingId: string };

export default function App() {
  const [view, setView] = useState<View>({ kind: "list" });
  const [refreshKey, setRefreshKey] = useState(0);
  const [status, setStatus] = useState<(RecordingStatusData & { meeting_id: string }) | null>(null);
  const [waveform, setWaveform] = useState<WaveformSample | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const handleEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case "recording.status":
        setStatus({ ...event.data, meeting_id: event.meeting_id });
        if (event.data.state === "stopped") setRefreshKey((k) => k + 1);
        break;
      case "recording.waveform":
        setWaveform({ ...event.data, at: Date.now() });
        break;
      case "app.detected":
        setNotice(
          event.data.app === "zoom"
            ? "Phát hiện Zoom đang mở — bạn có thể bắt đầu ghi cuộc họp."
            : "Phát hiện Microsoft Teams đang mở — bạn có thể bắt đầu ghi cuộc họp.",
        );
        break;
      default:
        break;
    }
  }, []);

  const connected = useAudioStream(handleEvent);
  const { meetings, error, reload } = useMeetings(refreshKey);

  const saved = useCallback(() => {
    setRefreshKey((k) => k + 1);
    reload();
  }, [reload]);

  return (
    <div className="app">
      <header className="app-header">
        <span className="brand">VoxScribe</span>
        <button
          className={`nav-btn ${view.kind === "list" ? "active" : ""}`}
          onClick={() => setView({ kind: "list" })}
        >
          Cuộc họp
        </button>
        <span className={`conn ${connected ? "on" : "off"}`}>
          {connected ? "Đã kết nối backend" : "Chưa kết nối backend"}
        </span>
      </header>

      {notice && (
        <div className="notice" onClick={() => setNotice(null)}>
          {notice} <b title="Đóng">×</b>
        </div>
      )}

      <main>
        {view.kind === "list" ? (
          <MeetingsList
            meetings={meetings}
            error={error}
            onSelect={(meetingId) => setView({ kind: "detail", meetingId })}
            onReload={reload}
          />
        ) : (
          <MeetingDetail
            meetingId={view.meetingId}
            onBack={() => setView({ kind: "list" })}
          />
        )}
      </main>

      <RecorderBar status={status} waveform={waveform} onSaved={saved} />
    </div>
  );
}
