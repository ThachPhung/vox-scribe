import { useCallback, useState } from "react";
import HomeView from "./components/HomeView";
import Icon from "./components/Icon";
import MeetingDetail from "./components/MeetingDetail";
import MeetingsList from "./components/MeetingsList";
import RecorderBar from "./components/RecorderBar";
import type { WaveformSample } from "./components/WaveformMeter";
import { useAudioStream } from "./hooks/useAudioStream";
import { useMeetings } from "./hooks/useMeetings";
import { formatClock, useRecorder, type LiveStatus } from "./hooks/useRecorder";
import type { WsEvent } from "./types";

const MEETING_APP_NAMES = { zoom: "Zoom", teams: "Microsoft Teams", meet: "Google Meet" } as const;

type View = { kind: "home" } | { kind: "detail"; meetingId: string };

export default function App() {
  const [view, setView] = useState<View>({ kind: "home" });
  const [refreshKey, setRefreshKey] = useState(0);
  const [status, setStatus] = useState<LiveStatus>(null);
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
        setNotice(`${MEETING_APP_NAMES[event.data.app]} đang mở. Bạn có muốn ghi cuộc họp này?`);
        break;
      default:
        break;
    }
  }, []);

  const connected = useAudioStream(handleEvent);
  const { meetings, error, reload } = useMeetings(refreshKey);

  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  const recorder = useRecorder(status, {
    onStarted: refresh,
    onStopped: (meetingId) => {
      refresh();
      setView({ kind: "detail", meetingId });
    },
  });

  const goHome = () => setView({ kind: "home" });
  const selectedId = view.kind === "detail" ? view.meetingId : undefined;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="wave" size={16} />
          </span>
          VoxScribe
        </div>

        <button
          className={`new-btn ${recorder.active ? "live" : ""} ${view.kind === "home" ? "current" : ""}`}
          onClick={goHome}
        >
          {recorder.active ? (
            <>
              <span className="rec-dot" /> Đang ghi · {formatClock(recorder.elapsed)}
            </>
          ) : (
            <>
              <Icon name="mic" size={16} /> Ghi cuộc họp mới
            </>
          )}
        </button>

        <MeetingsList
          meetings={meetings}
          error={error}
          selectedId={selectedId}
          onSelect={(meetingId) => setView({ kind: "detail", meetingId })}
          onReload={reload}
        />

        <div className={`conn ${connected ? "on" : "off"}`} title="Kết nối tới backend FastAPI (localhost:8000)">
          <span className="conn-dot" />
          {connected ? "Đã kết nối backend" : "Chưa kết nối backend"}
        </div>
      </aside>

      <main className="main">
        <div key={view.kind === "home" ? `home-${recorder.active}` : view.meetingId} className="view-enter view-root">
          {view.kind === "home" ? (
            <HomeView
              recorder={recorder}
              waveform={waveform}
              connected={connected}
              liveTitle={meetings.find((m) => m.id === recorder.meetingId)?.title}
            />
          ) : (
            <MeetingDetail meetingId={view.meetingId} refreshKey={refreshKey} />
          )}
        </div>
      </main>

      {view.kind !== "home" && <RecorderBar recorder={recorder} waveform={waveform} onOpen={goHome} />}

      {notice && (
        <div className="toast" role="status">
          <Icon name="mic" size={16} />
          <span>{notice}</span>
          {!recorder.active && (
            <button
              className="btn btn-accent btn-sm"
              onClick={() => {
                setNotice(null);
                goHome();
              }}
            >
              Ghi ngay
            </button>
          )}
          <button className="icon-btn" onClick={() => setNotice(null)} aria-label="Đóng thông báo">
            <Icon name="x" size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
