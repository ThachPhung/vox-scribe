// Gọi REST API lấy lịch sử cuộc họp
import { useCallback, useEffect, useState } from "react";
import { api } from "../services/apiClient";
import type { Meeting } from "../types";

export function useMeetings(refreshKey = 0) {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api
      .get<Meeting[]>("/meetings")
      .then((data) => {
        setMeetings(data);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(reload, [reload, refreshKey]);

  return { meetings, error, reload };
}
