// Khung xem biên bản 4 phần, tạo mới qua LLM khi chưa có.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../services/apiClient";
import type { MeetingReport, Report } from "../types";

interface Props {
  meetingId: string;
}

export default function ReportEditor({ meetingId }: Props) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get<Report>(`/meetings/${meetingId}/report`)
      .then((r) => {
        setReport(r);
        setError(null);
      })
      .catch((e: Error) => {
        if (e instanceof ApiError && e.status === 404) {
          setReport(null);
          setError(null);
        } else {
          setError(e.message);
        }
      });
  }, [meetingId]);

  useEffect(() => {
    setReport(null);
    load();
  }, [load]);

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.post<Report>(`/meetings/${meetingId}/report/generate`));
    } catch (e) {
      const err = e as ApiError;
      setError(
        err.status === 503
          ? "AI đang tắt hoặc không có mạng — kiểm tra cấu hình backend."
          : `Không tạo được biên bản: ${err.message}`,
      );
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="report">
        <p className="error-text">{error}</p>
        <button onClick={generate} disabled={busy}>
          {busy ? "Đang tạo…" : "Thử tạo biên bản"}
        </button>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="report">
        <p className="empty">Chưa có biên bản cho cuộc họp này.</p>
        <button onClick={generate} disabled={busy}>
          {busy ? "Đang tạo…" : "Tạo biên bản"}
        </button>
      </div>
    );
  }

  const content: MeetingReport = report.content;
  return (
    <div className="report">
      <div className="report-meta">
        <span>Bản {report.revision}</span>
        {report.stale && <span className="badge stale">Transcript đã đổi sau khi tạo</span>}
      </div>
      {report.warnings.length > 0 && (
        <ul className="report-warnings">
          {report.warnings.map((w) => (
            <li key={w}>⚠ {w}</li>
          ))}
        </ul>
      )}

      <ReportSection title="Mục tiêu" items={content.goals.map((i) => i.content)} />
      <ReportSection title="Quyết định đã chốt" items={content.decisions.map((i) => i.content)} />
      <ReportSection title="Vấn đề còn bỏ ngỏ" items={content.open_issues.map((i) => i.content)} />

      <section className="report-section">
        <h3>Bảng phân công công việc</h3>
        {content.action_items.length === 0 ? (
          <p className="empty">Không có mục việc nào.</p>
        ) : (
          <table className="action-table">
            <thead>
              <tr>
                <th>Việc</th>
                <th>Người phụ trách</th>
                <th>Hạn</th>
              </tr>
            </thead>
            <tbody>
              {content.action_items.map((item, i) => (
                <tr key={`${item.task}-${i}`}>
                  <td>{item.task}</td>
                  <td>{item.owner ?? "—"}</td>
                  <td>{item.deadline ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <div className="report-actions">
        <button onClick={load} disabled={busy}>
          Tải lại
        </button>
        <button onClick={generate} disabled={busy}>
          {busy ? "Đang tạo…" : "Tạo lại bằng AI"}
        </button>
      </div>
    </div>
  );
}

function ReportSection({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="report-section">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="empty">Trống.</p>
      ) : (
        <ul>
          {items.map((item, i) => (
            <li key={`${item}-${i}`}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
