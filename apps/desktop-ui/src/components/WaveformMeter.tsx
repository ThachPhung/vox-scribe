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
}

const HISTORY = 96;
const STALE_MS = 2000;

export default function WaveformMeter({ active, waveform }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const propsRef = useRef<Props>({ active, waveform });
  propsRef.current = { active, waveform };

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const history: { l: number; r: number }[] = Array.from({ length: HISTORY }, () => ({
      l: 0,
      r: 0,
    }));
    let raf = 0;
    let phase = 0;

    const draw = () => {
      const { active, waveform } = propsRef.current;
      const fresh = waveform !== null && Date.now() - waveform.at < STALE_MS;
      let l = 0;
      let r = 0;
      let mock = false;
      if (active) {
        if (fresh && waveform) {
          l = waveform.left;
          r = waveform.right;
        } else {
          // Nguồn dữ liệu thật chưa tới – mức mô phỏng để test giao diện.
          mock = true;
          phase += 0.18;
          l = Math.min(1, 0.18 + 0.12 * Math.sin(phase) + Math.random() * 0.06);
          r = Math.min(1, 0.18 + 0.12 * Math.cos(phase * 0.85) + Math.random() * 0.06);
        }
      }
      history.push({ l, r });
      history.shift();

      const { width, height } = canvas;
      ctx.clearRect(0, 0, width, height);
      const mid = height / 2;
      const barW = width / HISTORY;
      for (let i = 0; i < HISTORY; i++) {
        const sample = history[i];
        const x = i * barW;
        ctx.fillStyle = "#4f8cff";
        ctx.fillRect(x, mid - 2 - sample.l * (mid - 6), Math.max(1, barW - 1), sample.l * (mid - 6));
        ctx.fillStyle = "#3ecf8e";
        ctx.fillRect(x, mid + 2, Math.max(1, barW - 1), sample.r * (mid - 6));
      }
      ctx.strokeStyle = "#2a2f3a";
      ctx.beginPath();
      ctx.moveTo(0, mid);
      ctx.lineTo(width, mid);
      ctx.stroke();

      ctx.font = "11px system-ui";
      ctx.fillStyle = "#8b93a7";
      if (!active) {
        ctx.fillText("Không đang ghi", 8, 14);
      } else if (mock) {
        ctx.fillText("sóng mô phỏng — chờ dữ liệu từ backend", 8, 14);
      }

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, []);

  return <canvas ref={canvasRef} className="waveform" width={640} height={72} />;
}
