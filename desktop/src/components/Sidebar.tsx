import type { BackendStatus } from "../hooks/useBackendStatus";
import type { CaptureStatus } from "../types/capture";
import { StatusBadge } from "./StatusBadge";

export type Page = "dashboard" | "monitor" | "review" | "journal" | "training";

const NAV: { id: Page; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "monitor", label: "Screen Monitor" },
  { id: "review", label: "Move Review" },
  { id: "journal", label: "Nhật ký tư duy" },
  { id: "training", label: "Luyện tập" },
];

export function Sidebar({ page, onNavigate, status, backend }: { page: Page; onNavigate: (p: Page) => void; status: CaptureStatus; backend: BackendStatus }) {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-slate-800 bg-slate-950 p-4">
      <div className="mb-8">
        <div className="text-lg font-semibold text-slate-100">Xiangqi Coach</div>
        <div className="text-xs text-slate-500">Live Screen Training</div>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV.map((n) => (
          <button
            key={n.id}
            onClick={() => onNavigate(n.id)}
            aria-current={page === n.id ? "page" : undefined}
            className={`rounded-md px-3 py-2 text-left text-sm transition ${
              page === n.id ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
            }`}
          >
            {n.label}
          </button>
        ))}
      </nav>
      <div className="mt-auto space-y-3 border-t border-slate-800 pt-4">
        <StatusBadge status={status} />
        <BackendLines b={backend} />
      </div>
    </aside>
  );
}

function Line({ ok, label, title }: { ok: boolean | null; label: string; title?: string }) {
  const dot = ok === null ? "bg-slate-500" : ok ? "bg-emerald-500" : "bg-amber-500";
  return (
    <li className="flex items-center gap-2" title={title}>
      <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden />
      {label}
    </li>
  );
}

function BackendLines({ b }: { b: BackendStatus }) {
  if (!b.checked) return <p className="text-xs text-slate-500">Đang kiểm tra backend…</p>;
  if (!b.health) return <p role="status" className="text-xs text-amber-300" title={b.error ?? undefined}>Backend chưa chạy</p>;
  return (
    <ul role="status" className="space-y-1 text-xs text-slate-400">
      <Line ok={b.health.status === "ok"} label={b.health.status === "ok" ? "Backend: sẵn sàng" : "Backend: lỗi cơ sở dữ liệu"} />
      <Line ok={b.engine?.available ?? null} label={b.engine?.available ? "Pikafish: sẵn sàng" : "Pikafish: chưa có"} title={b.engine?.message ?? b.engine?.last_error ?? undefined} />
      <Line ok={b.coach?.available ?? null} label={b.coach?.available ? `AI Coach: ${[b.coach.provider, b.coach.model].filter(Boolean).join(" · ") || "bật"}` : "AI Coach: tắt"} title={b.coach?.reason ?? undefined} />
    </ul>
  );
}
