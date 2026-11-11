// Danh sách cuộc họp ở thanh bên, nhóm theo ngày, có ô tìm kiếm.
import { useMemo, useState } from "react";
import type { Meeting } from "../types";
import { dayGroup, fmtDay, fmtDuration, fmtTime } from "../utils";
import Icon from "./Icon";

interface Props {
  meetings: Meeting[];
  error: string | null;
  selectedId?: string;
  onSelect: (meetingId: string) => void;
  onReload: () => void;
}

export default function MeetingsList({ meetings, error, selectedId, onSelect, onReload }: Props) {
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const map = new Map<string, Meeting[]>();
    for (const m of meetings) {
      if (q && !m.title.toLowerCase().includes(q)) continue;
      const key = dayGroup(m.started_at);
      map.set(key, [...(map.get(key) ?? []), m]);
    }
    return [...map.entries()];
  }, [meetings, query]);

  return (
    <nav className="meetings-list" aria-label="Danh sách cuộc họp">
      <div className="search">
        <Icon name="search" size={15} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Tìm cuộc họp"
          aria-label="Tìm cuộc họp"
        />
      </div>

      <div className="list-head">
        <span>Cuộc họp</span>
        <button className="icon-btn" onClick={onReload} title="Làm mới" aria-label="Làm mới danh sách">
          <Icon name="refresh" size={15} />
        </button>
      </div>

      <div className="list-scroll">
        {error && <p className="list-note error">Không tải được danh sách: {error}</p>}
        {!error && meetings.length === 0 && <p className="list-note">Chưa có cuộc họp nào.</p>}
        {!error && meetings.length > 0 && groups.length === 0 && (
          <p className="list-note">Không có cuộc họp khớp “{query}”.</p>
        )}

        {groups.map(([group, items]) => {
          const recent = group === "Hôm nay" || group === "Hôm qua";
          return (
            <div key={group} className="list-group">
              <div className="group-label">{group}</div>
              {items.map((m) => (
                <button
                  key={m.id}
                  className={`meeting-item ${m.id === selectedId ? "selected" : ""}`}
                  onClick={() => onSelect(m.id)}
                  aria-current={m.id === selectedId ? "page" : undefined}
                >
                  <span className="meeting-title">
                    {m.status === "recording" && <span className="rec-dot" title="Đang ghi" />}
                    {m.title}
                  </span>
                  <span className="meeting-meta">
                    {recent ? fmtTime(m.started_at) : fmtDay(m.started_at)} ·{" "}
                    {m.status === "recording" ? "Đang ghi" : fmtDuration(m.duration_sec)}
                  </span>
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </nav>
  );
}
