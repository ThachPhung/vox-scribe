// Nhận sự kiện trạng thái thu âm / sóng âm qua WebSocket, tự nối lại nếu backend chưa mở.
import { useEffect, useRef, useState } from "react";
import { WS_URL } from "../services/apiClient";
import type { WsEvent } from "../types";

export function useAudioStream(onEvent: (event: WsEvent) => void): boolean {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      socket = new WebSocket(`${WS_URL}/ws`);
      socket.onopen = () => setConnected(true);
      socket.onmessage = (e) => {
        try {
          handler.current(JSON.parse(e.data) as WsEvent);
        } catch {
          // bỏ qua gói hỏng
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!closed) timer = setTimeout(connect, 2000);
      };
      socket.onerror = () => socket?.close();
    };
    connect();

    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return connected;
}
