// Danh sách cuộc họp, bấm một dòng để mở chi tiết.
import { fmtDateTime, fmtDuration } from "../utils";
import type { Meeting } from "../types";

interface Props {
  meetings: Meeting[];
  error: string | null;
  selectedId?: string;
  onSelect: (meetingId: string) => void;
  onReload: () => void;
}

export default function MeetingsList({ meetings, error, selectedId, onSelect, onReload }: Props) {
  return (
    <section className="meetings-list">
      <div className="section-head">
        <h2>Danh sách cuộc họp</h2>
        <button className="ghost" onClick={onReload}>
          Làm mới
        </button>
      </div>

      {error && <p className="error-text">Không tải được danh sách: {error}</p>}
      {!error && meetings.length === 0 && (
        <p className="empty">Chưa có cuộc họp nào. Bấm “Bắt đầu ghi” ở thanh dưới.</p>
      )}

      {meetings.length > 0 && (
        <table className="meetings-table">
          <thead>
            <tr>
              <th>Tên cuộc họp</th>
              <th>Thời gian</th>
              <th>Dài</th>
              <th>Trạng thái</th>
            </tr>
          </thead>
          <tbody>
            {meetings.map((m) => (
              <tr
                key={m.id}
                className={m.id === selectedId ? "selected" : ""}
                onClick={() => onSelect(m.id)}
              >
                <td>{m.title}</td>
                <td>{fmtDateTime(m.started_at)}</td>
                <td>{fmtDuration(m.duration_sec)}</td>
                <td>
                  <span className={`badge ${m.status}`}>
                    {m.status === "recording" ? "Đang ghi" : "Đã ghi"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
