import type { CaptureStatus } from "../types/capture";

const STYLES: Record<CaptureStatus, { label: string; dot: string; text: string }> = {
  idle: { label: "Chưa chia sẻ", dot: "bg-slate-500", text: "text-slate-300" },
  requesting: { label: "Đang chờ chọn nguồn…", dot: "bg-amber-400 animate-pulse", text: "text-amber-300" },
  sharing: { label: "Đang chia sẻ màn hình", dot: "bg-red-500 animate-pulse", text: "text-red-300" },
};

export function StatusBadge({ status }: { status: CaptureStatus }) {
  const s = STYLES[status];
  return (
    <span role="status" className={`inline-flex items-center gap-2 text-sm font-medium ${s.text}`}>
      <span className={`h-2.5 w-2.5 rounded-full ${s.dot}`} aria-hidden />
      {s.label}
    </span>
  );
}
