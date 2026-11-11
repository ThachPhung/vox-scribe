// Cấu hình kết nối tới FastAPI (localhost:8000)
export const API_URL = "http://localhost:8000";
export const WS_URL = "ws://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // body không phải JSON, giữ message mặc định
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

export const api = {
  get: <T = unknown>(p: string) => request<T>(p),
  post: <T = unknown>(p: string, body?: unknown) =>
    request<T>(p, { method: "POST", body: JSON.stringify(body) }),
};
