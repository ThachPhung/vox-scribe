// Hai chế độ ghi, gửi lên backend qua trường capture_mode của cuộc họp.
// TV2 đọc capture_mode khi chép lời: "room" thì tách nhiều người nói trên cùng một mic.
import type { IconName } from "./components/Icon";
import type { CaptureMode } from "./types";

export interface CaptureModeInfo {
  value: CaptureMode;
  icon: IconName;
  label: string;
  hint: string;
}

export const CAPTURE_MODES: readonly CaptureModeInfo[] = [
  {
    value: "headset",
    icon: "headset",
    label: "Họp online",
    hint: "Meet, Zoom, Teams. Mic là bạn, loa là người khác",
  },
  {
    value: "room",
    icon: "room",
    label: "Họp tại chỗ",
    hint: "Nhiều người nói chung một mic, AI tách từng người",
  },
];

export function captureModeInfo(mode: CaptureMode | null): CaptureModeInfo | null {
  return CAPTURE_MODES.find((m) => m.value === mode) ?? null;
}
