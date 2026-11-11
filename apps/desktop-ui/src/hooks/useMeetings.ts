// Gọi REST API lấy lịch sử và báo cáo
import { useEffect, useState } from "react";
import { api } from "../services/apiClient";

export function useMeetings() {
  const [meetings, setMeetings] = useState<unknown[]>([]);
  useEffect(() => {
    api.get("/meetings").then(setMeetings).catch(console.error);
  }, []);
  return meetings;
}
