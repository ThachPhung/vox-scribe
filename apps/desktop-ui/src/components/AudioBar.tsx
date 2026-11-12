// Nghe lại và lưu file ghi âm (WAV stereo: trái = mic, phải = loa) của một cuộc họp.
import { invoke, isTauri } from "@tauri-apps/api/core";
import { useState } from "react";
import { API_URL } from "../services/apiClient";
import Icon from "./Icon";

interface Props {
  meetingId: string;
  title: string;
  /** Đường dẫn file WAV trên máy (backend lưu trong meetings.audio_path). */
  audioPath: string;
}

/** Bỏ ký tự Windows không cho dùng trong tên file, giống backend. */
function safeFilename(title: string): string {
  return title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-").replace(/^[ .]+|[ .]+$/g, "") || "cuoc-hop";
}

/** Trình duyệt thường: tải qua blob cùng origin (link thẳng sang :8000 bị bỏ qua thuộc tính download). */
async function downloadInBrowser(src: string, filename: string): Promise<void> {
  const res = await fetch(src);
  if (!res.ok) throw new Error(res.status === 404 ? "Không còn file ghi âm" : `Lỗi ${res.status}`);
  const url = URL.createObjectURL(await res.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export default function AudioBar({ meetingId, title, audioPath }: Props) {
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const src = `${API_URL}/meetings/${meetingId}/audio`;

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      if (isTauri()) {
        // App desktop: WebView không tự tải file, nên mở hộp thoại "Lưu thành…" của Windows.
        const saved = await invoke<string | null>("save_recording", {
          source: audioPath,
          suggestedName: safeFilename(title),
        });
        if (saved) setMessage({ kind: "ok", text: `Đã lưu: ${saved}` });
      } else {
        await downloadInBrowser(src, `${safeFilename(title)}.wav`);
      }
    } catch (e) {
      const reason = e instanceof Error ? e.message : String(e);
      setMessage({ kind: "error", text: `Không lưu được: ${reason}` });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="audio-bar">
      {/* Ẩn mục "Download" trong menu ba chấm của WebView: nó không chạy trong app Tauri,
          việc lưu file đi qua nút "Tải âm thanh" bên cạnh. */}
      <audio controls controlsList="nodownload" preload="metadata" src={src} aria-label="Nghe lại bản ghi" />
      <button className="btn btn-sm" onClick={save} disabled={saving} title="Lưu file WAV về máy">
        <Icon name="download" size={14} />
        {saving ? "Đang lưu…" : "Tải âm thanh"}
      </button>
      {message && <span className={`audio-msg ${message.kind}`}>{message.text}</span>}
    </div>
  );
}
