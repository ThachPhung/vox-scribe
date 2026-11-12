// Khung xem biên bản 4 phần, tạo mới qua LLM khi chưa có.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../services/apiClient";
import type { MeetingReport, Report, ReportItem } from "../types";
import CopyButton from "./CopyButton";
import Icon from "./Icon";

interface Props {
  meetingId: string;
}

export default function ReportEditor({ meetingId }: Props) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
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
      })
      .finally(() => setLoading(false));
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
          ? "AI đang tắt hoặc không có mạng. Kiểm tra cấu hình backend."
          : `Không tạo được biên bản: ${err.message}`,
      );
    } finally {
      setBusy(false);
    }
  };

  const generateLabel = busy ? "Đang tạo…" : report ? "Tạo lại" : "Tạo biên bản";

  return (
    <div className="pane">
      <div className="pane-head">
        <h2>Biên bản</h2>
        {report && <span className="chip">Bản {report.revision}</span>}
        <div className="pane-actions">
          {report && <CopyButton getText={() => reportToText(report.content)} />}
          {report && (
            <button className="btn btn-ghost" onClick={load} disabled={busy} title="Tải lại biên bản">
              <Icon name="refresh" size={15} />
            </button>
          )}
          {(report || error) && (
            <button className="btn btn-accent" onClick={generate} disabled={busy}>
              <Icon name="sparkles" size={15} />
              {generateLabel}
            </button>
          )}
        </div>
      </div>

      <div className="pane-body">
        {error && (
          <div className="callout danger">
            <Icon name="alert" size={16} />
            <span>{error}</span>
          </div>
        )}

        {!report && !error && loading && <p className="pane-empty">Đang tải…</p>}

        {!report && !error && !loading && (
          <div className="empty-state">
            <div className="empty-icon">
              <Icon name="file" size={22} />
            </div>
            <h3>Chưa có biên bản</h3>
            <p>AI sẽ tóm tắt mục tiêu, quyết định, vấn đề còn bỏ ngỏ và bảng phân công từ lời thoại.</p>
            <button className="btn btn-accent" onClick={generate} disabled={busy}>
              <Icon name="sparkles" size={15} />
              {generateLabel}
            </button>
          </div>
        )}

        {report && <ReportBody report={report} />}
      </div>
    </div>
  );
}

function ReportBody({ report }: { report: Report }) {
  const content: MeetingReport = report.content;
  return (
    <article className="report">
      {(report.stale || report.warnings.length > 0) && (
        <div className="callout warning">
          <Icon name="alert" size={16} />
          <div>
            {report.stale && <p>Lời thoại đã thay đổi sau khi tạo biên bản. Bấm “Tạo lại” để cập nhật.</p>}
            {report.warnings.map((w) => (
              <p key={w}>{w}</p>
            ))}
          </div>
        </div>
      )}

      <ReportSection title="Mục tiêu" items={content.goals} />
      <ReportSection title="Quyết định đã chốt" items={content.decisions} />
      <ReportSection title="Vấn đề còn bỏ ngỏ" items={content.open_issues} />

      <section className="report-section">
        <h3>Bảng phân công</h3>
        {content.action_items.length === 0 ? (
          <p className="muted">Không có mục việc nào.</p>
        ) : (
          <table className="action-table">
            <thead>
              <tr>
                <th>Việc</th>
                <th>Phụ trách</th>
                <th>Hạn</th>
              </tr>
            </thead>
            <tbody>
              {content.action_items.map((item, i) => (
                <tr key={`${item.task}-${i}`}>
                  <td>{item.task}</td>
                  <td>{item.owner ? <span className="owner">{item.owner}</span> : <span className="missing">Chưa rõ</span>}</td>
                  <td>{item.deadline ?? <span className="missing">Chưa rõ</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </article>
  );
}

function ReportSection({ title, items }: { title: string; items: ReportItem[] }) {
  return (
    <section className="report-section">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="muted">Không có.</p>
      ) : (
        <ul>
          {items.map((item, i) => (
            <li key={`${item.content}-${i}`}>
              {item.content}
              {item.evidence_at && <span className="evidence">{item.evidence_at}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Biên bản dạng văn bản thuần để sao chép sang chat/email. */
function reportToText(c: MeetingReport): string {
  const list = (title: string, items: ReportItem[]) =>
    `${title}\n${items.length ? items.map((i) => `- ${i.content}`).join("\n") : "- (không có)"}`;
  const actions = c.action_items.length
    ? c.action_items.map((a) => `- ${a.task} | ${a.owner ?? "Chưa rõ"} | ${a.deadline ?? "Chưa rõ"}`).join("\n")
    : "- (không có)";
  return [
    list("Mục tiêu", c.goals),
    list("Quyết định đã chốt", c.decisions),
    list("Vấn đề còn bỏ ngỏ", c.open_issues),
    `Bảng phân công (việc | phụ trách | hạn)\n${actions}`,
  ].join("\n\n");
}
