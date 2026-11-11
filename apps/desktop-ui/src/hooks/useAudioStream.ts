// Nhận trạng thái thu âm qua WebSocket
import { useEffect, useState } from "react";
import { WS_URL } from "../services/apiClient";

export function useAudioStream() {
  const [status, setStatus] = useState<unknown>(null);
  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}/ws`);
    ws.onmessage = (e) => setStatus(JSON.parse(e.data));
    return () => ws.close();
  }, []);
  return status;
}
