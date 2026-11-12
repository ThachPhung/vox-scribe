// Nghe lại và tải file ghi âm (WAV stereo: trái = mic, phải = loa) của một cuộc họp.
import { useState } from "react";
import { API_URL } from "../services/apiClient";
import Icon from "./Icon";

interface Props {
  meetingId: string;
  title: string;
}

/** Bỏ ký tự Windows không cho dùng trong tên file, giống backend. */
function safeFilename(title: string): string {
  return title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-").replace(/^[ .]+|[ .]+$/g, "") || "cuoc-hop";
}

export default function AudioBar({ meetingId, title }: Props) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const src = `${API_URL}/meetings/${meetingId}/audio`;

  // Tải qua blob cùng origin: thẻ <a download> trỏ thẳng sang localhost:8000 (khác origin)
  // sẽ bị bỏ qua thuộc tính download và mở file ngay trong cửa sổ app.
  const download = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(src);
      if (!res.ok) throw new Error(res.status === 404 ? "Không còn file ghi âm" : `Lỗi ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${safeFilename(title)}.wav`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) {
      setError(`Không tải được: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="audio-bar">
      <audio controls preload="metadata" src={src} aria-label="Nghe lại bản ghi" />
      <button className="btn btn-sm" onClick={download} disabled={saving} title="Lưu file WAV về máy">
        <Icon name="download" size={14} />
        {saving ? "Đang tải…" : "Tải âm thanh"}
      </button>
      {error && <span className="audio-error">{error}</span>}
    </div>
  );
}
