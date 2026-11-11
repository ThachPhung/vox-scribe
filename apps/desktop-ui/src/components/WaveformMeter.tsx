// Vẽ sóng âm hai kênh (trái = mic, phải = hệ thống) từ mức WS nhận được.
// Khi đang ghi mà chưa có dữ liệu thật từ backend thì vẽ mức mô phỏng để giữ khung.
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
    let phase = 0;
    let frame = 0;

    const draw = () => {
      raf = requestAnimationFrame(draw);
      // ~30 fps là đủ mượt và nhẹ CPU.
      if (frame++ % 2) return;
      const { active, waveform } = propsRef.current;
      let l = 0;
      let r = 0;
      if (active) {
        if (isWaveformFresh(waveform) && waveform) {
          l = waveform.left;
          r = waveform.right;
        } else {
          phase += 0.18;
          l = Math.min(1, 0.18 + 0.12 * Math.sin(phase) + Math.random() * 0.06);
          r = Math.min(1, 0.18 + 0.12 * Math.cos(phase * 0.85) + Math.random() * 0.06);
        }
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
        const { l: sl, r: sr } = history[i];
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
