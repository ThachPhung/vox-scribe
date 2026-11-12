// Vẽ sóng âm hai kênh (trái = mic, phải = hệ thống) từ mức WS nhận được.
// Khi đang ghi luôn có một dải màu "thở" nhẹ làm nền; mức âm thật từ backend vẽ chồng lên.
import { useEffect, useRef } from "react";

export interface WaveformSample {
  left: number;
  right: number;
  at: number;
}

interface Props {
  active: boolean;
  waveform: WaveformSample | null;
  /** Số cột sóng hiển thị. */
  bars?: number;
  className?: string;
}

const STALE_MS = 2000;
// Lớp nền "thở" khi đang ghi: dao động quanh 0,18 (± 0,12), giống dải màu bản trước.
const IDLE_BASE = 0.18;
const IDLE_SWING = 0.12;
const IDLE_JITTER = 0.06;
const IDLE_SPREAD = 0.22; // độ lệch pha giữa hai cột cạnh nhau → sóng chạy ngang

/** true nếu backend vừa gửi mức sóng gần đây. */
export function isWaveformFresh(waveform: WaveformSample | null): boolean {
  return waveform !== null && Date.now() - waveform.at < STALE_MS;
}

export default function WaveformMeter({ active, waveform, bars = 96, className = "" }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const propsRef = useRef({ active, waveform });
  propsRef.current = { active, waveform };

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    // Canvas luôn khớp kích thước CSS × devicePixelRatio để nét không bị nhòe.
    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const { width, height } = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    const history = Array.from({ length: bars }, () => ({ l: 0, r: 0 }));
    let raf = 0;
    let frame = 0;
    let smoothL = 0;
    let smoothR = 0;
    let phase = 0;

    const draw = () => {
      raf = requestAnimationFrame(draw);
      // ~30 fps là đủ mượt và nhẹ CPU.
      if (frame++ % 2) return;
      const { active, waveform } = propsRef.current;
      let l = 0;
      let r = 0;
      if (active) {
        const fresh = waveform !== null && isWaveformFresh(waveform);
        // Mức thật: căn bậc hai để tiếng nói nhỏ vẫn nhìn thấy; attack nhanh, release chậm cho mượt.
        const targetL = fresh ? Math.sqrt(waveform.left) : 0;
        const targetR = fresh ? Math.sqrt(waveform.right) : 0;
        smoothL = targetL > smoothL ? targetL : smoothL * 0.82 + targetL * 0.18;
        smoothR = targetR > smoothR ? targetR : smoothR * 0.82 + targetR * 0.18;
        l = Math.min(1, smoothL);
        r = Math.min(1, smoothR);
        phase += 0.16;
      } else {
        smoothL = 0;
        smoothR = 0;
      }
      history.push({ l, r });
      history.shift();

      const style = getComputedStyle(canvas);
      const micColor = style.getPropertyValue("--wave-mic").trim() || "#2563eb";
      const sysColor = style.getPropertyValue("--wave-sys").trim() || "#0d9488";
      const idleColor = style.getPropertyValue("--wave-idle").trim() || "#d4d4d8";

      const { width, height } = canvas;
      ctx.clearRect(0, 0, width, height);
      const mid = height / 2;
      const gap = Math.max(1, Math.round(width / bars / 3));
      const slot = width / bars;
      const barW = Math.max(1, slot - gap);
      const maxH = mid - 1;
      const minH = Math.max(1, Math.round(height / 40));
      for (let i = 0; i < bars; i++) {
        // Đang ghi: cả dải màu "thở" thành sóng chạy ngang ngay từ giây đầu (kể cả lúc im lặng);
        // mức âm thật cuộn từ phải sang và cao hơn hẳn lớp nền này.
        const wave = phase - i * IDLE_SPREAD;
        const sl = active
          ? Math.max(history[i].l, IDLE_BASE + IDLE_SWING * Math.sin(wave) + IDLE_JITTER * Math.random())
          : history[i].l;
        const sr = active
          ? Math.max(history[i].r, IDLE_BASE + IDLE_SWING * Math.cos(wave * 0.85) + IDLE_JITTER * Math.random())
          : history[i].r;
        const x = i * slot;
        const hl = Math.max(minH, sl * maxH);
        const hr = Math.max(minH, sr * maxH);
        ctx.fillStyle = sl > 0 ? micColor : idleColor;
        roundRect(ctx, x, mid - hl, barW, hl);
        ctx.fillStyle = sr > 0 ? sysColor : idleColor;
        roundRect(ctx, x, mid + 1, barW, hr);
      }
    };
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [bars]);

  return <canvas ref={canvasRef} className={`waveform ${className}`} aria-hidden="true" />;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number) {
  const r = Math.min(w / 2, h / 2, 3);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
  ctx.fill();
}
