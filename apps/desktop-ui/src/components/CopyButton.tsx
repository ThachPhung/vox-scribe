// Nút sao chép văn bản, đổi sang dấu tích trong chốc lát khi đã chép.
import { useEffect, useState } from "react";
import Icon from "./Icon";

interface Props {
  getText: () => string;
  label?: string;
}

export default function CopyButton({ getText, label = "Sao chép" }: Props) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(getText());
      setCopied(true);
    } catch {
      // Clipboard bị chặn: bỏ qua, người dùng vẫn có thể bôi đen để chép.
    }
  };

  return (
    <button className="btn btn-ghost" onClick={copy} title={label}>
      <Icon name={copied ? "check" : "copy"} size={15} />
      {copied ? "Đã chép" : label}
    </button>
  );
}
