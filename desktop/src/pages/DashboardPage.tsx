import { useState } from "react";
import { Card, ErrorText } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { useLoad } from "../hooks/useLoad";
import type { ScreenCapture } from "../hooks/useScreenCapture";
import { api, errorText } from "../services/backend";
import type { PeriodStat } from "../types/api";

// Honest status: every module has code, but nothing has been verified on Windows or against real Ziga.vn frames.
const ROADMAP: { step: string; done: boolean }[] = [
  { step: "Chia sẻ màn hình, chụp khung hình", done: true },
  { step: "Nhận diện bàn cờ 9×10 và quân cờ (hiệu chỉnh theo theme)", done: true },
  { step: "Theo dõi nước đi, buổi tập, hoàn tác", done: true },
  { step: "Phân tích bằng Pikafish", done: true },
  { step: "AI Thinking Coach (tùy chọn, cần khóa API)", done: true },
  { step: "Nhật ký tư duy, Luyện tập, Thống kê, xuất/sao lưu dữ liệu", done: true },
  { step: "Đo độ chính xác nhận diện trên ảnh Ziga.vn thật", done: false },
  { step: "Kiểm thử và đóng gói trên Windows 10/11", done: false },
];
const NOT_ENOUGH = "Chưa đủ dữ liệu";
const score = (v: number | null) => (v === null ? NOT_ENOUGH : `${Math.round(v)}/100`);

export function DashboardPage({ capture, onOpenMonitor }: { capture: ScreenCapture; onOpenMonitor: () => void }) {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-100">Dashboard</h1>
        <p className="text-sm text-slate-400">Công cụ huấn luyện tính toán cờ Tướng — không phải bot chơi cờ.</p>
      </header>

      <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Chia sẻ màn hình</h2>
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <StatusBadge status={capture.status} />
            {capture.source && <p className="mt-1 truncate text-xs text-slate-500">Nguồn: {capture.source}</p>}
          </div>
          <button onClick={onOpenMonitor} className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500">
            Mở Screen Monitor
          </button>
        </div>
      </section>

      <Stats />
      <DataTools />

      <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Lộ trình phát triển</h2>
        <ol className="space-y-2 text-sm">
          {ROADMAP.map((r) => (
            <li key={r.step} className={r.done ? "text-slate-300" : "font-medium text-amber-300"}>
              {r.done ? "✓ " : "… "}
              {r.step}
              {!r.done && " (chưa làm)"}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function Stats() {
  const { data: d, error } = useLoad(api.stats);
  return (
    <Card title="Thống kê luyện tập">
      <ErrorText error={error} />
      {d && (
        <div className="space-y-4 text-sm">
          {d.message && <p className="text-slate-500">{d.message}</p>}
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Buổi tập" value={String(d.total_sessions)} />
            <Stat label="Nước đã đánh giá" value={String(d.total_reviewed_moves)} />
            <Stat label="Điểm tư duy TB" value={score(d.avg_thinking_score)} sub={d.thinking_samples ? `${d.thinking_samples} nước` : undefined} />
            <Stat label="Chất lượng nước đi TB" value={score(d.avg_move_quality)} sub={d.move_quality_samples ? `${d.move_quality_samples} nước` : undefined} />
          </dl>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Lỗi thường gặp</h3>
            {d.common_mistakes.length ? (
              <ul className="text-slate-300">{d.common_mistakes.map((m) => <li key={m.component}>{m.label}: {m.count}</li>)}</ul>
            ) : <p className="text-slate-500">{NOT_ENOUGH}</p>}
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Kỹ năng cần cải thiện</h3>
            {d.skills_to_improve.length ? (
              <ul className="text-slate-300">{d.skills_to_improve.map((k) => <li key={k.component}>{k.label}: {Math.round(k.avg_score * 100)}% ({k.samples} câu trả lời)</li>)}</ul>
            ) : (
              <p className="text-slate-500">{d.skills_message ?? "Các kỹ năng đủ dữ liệu đều đang đạt điểm tối đa — tiếp tục duy trì."}</p>
            )}
          </div>
          <Weekly rows={d.weekly} />
        </div>
      )}
    </Card>
  );
}

function Weekly({ rows }: { rows: PeriodStat[] }) {
  if (!rows.length) return null;
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Theo tuần</h3>
      <table className="w-full text-left">
        <thead className="text-xs text-slate-500"><tr><th>Tuần</th><th>Nước</th><th>Tư duy TB</th><th>Nước đi TB</th></tr></thead>
        <tbody className="text-slate-300">
          {rows.map((r) => (
            <tr key={r.period} className="border-t border-slate-800">
              <td className="py-1 font-mono text-xs">{r.period}</td>
              <td>{r.reviews}</td>
              <td><Bar v={r.avg_thinking} /></td>
              <td><Bar v={r.avg_move_quality} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Bar({ v }: { v: number | null }) {
  if (v === null) return <span className="text-xs text-slate-500">{NOT_ENOUGH}</span>;
  return (
    <span className="flex items-center gap-2">
      <span className="h-2 w-24 rounded bg-slate-800"><span className="block h-2 rounded bg-emerald-500" style={{ width: `${Math.max(0, Math.min(100, v))}%` }} /></span>
      <span className="text-xs">{Math.round(v)}</span>
    </span>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-100">{value}</dd>
      {sub && <dd className="text-xs text-slate-400">{sub}</dd>}
    </div>
  );
}

function DataTools() {
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<string>) {
    setError(null);
    setMsg(null);
    try {
      setMsg(await fn());
    } catch (e) {
      setError(errorText(e));
    }
  }

  const exportJson = () => run(async () => {
    const blob = await api.exportData();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `xiangqi-coach-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); // give the download time to start
    return "Đã xuất dữ liệu (JSON).";
  });
  const backup = () => run(async () => {
    const b = await api.backup();
    return `Đã sao lưu ${Math.round(b.size_bytes / 1024)} KB vào: ${b.path}`;
  });

  return (
    <Card title="Dữ liệu">
      <div className="flex flex-wrap gap-2">
        <button onClick={exportJson} className="rounded-md bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600">Xuất dữ liệu (JSON)</button>
        <button onClick={backup} className="rounded-md bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600">Sao lưu</button>
      </div>
      {msg && <p className="mt-2 break-all text-sm text-emerald-300">{msg}</p>}
      <ErrorText error={error} />
    </Card>
  );
}
