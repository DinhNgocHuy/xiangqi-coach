import { Card, ErrorText } from "../components/Card";
import { useLoad } from "../hooks/useLoad";
import { api } from "../services/backend";
import type { Pattern } from "../types/api";

const DIRECTION: Record<Pattern["direction"], string> = {
  improving: "Đang tiến bộ",
  worsening: "Đang kém đi",
  flat: "Không đổi",
  insufficient_data: "Chưa đủ dữ liệu",
};
const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
const mistakes = () => api.mistakes(50);

export function JournalPage() {
  const patterns = useLoad(api.patterns);
  const list = useLoad(mistakes);
  const p = patterns.data;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-100">Nhật ký tư duy</h1>
        <p className="text-sm text-slate-400">Lỗi tư duy được ghi từ các nước bạn đã tự đánh giá. Phần bạn không trả lời không bị tính là lỗi.</p>
      </header>

      <Card title="Mẫu lỗi lặp lại">
        <ErrorText error={patterns.error} />
        {p && (
          <>
            <p className="mb-3 text-sm text-slate-400">
              {p.message ?? `${p.total_mistakes} lỗi từ ${p.reviewed_moves} nước đã đánh giá.`} <span className="text-xs text-slate-500">{p.rule}</span>
            </p>
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-slate-500">
                <tr><th className="py-1">Kỹ năng</th><th>Số lỗi</th><th>Tỉ lệ</th><th>Gần đây</th><th>Xu hướng</th></tr>
              </thead>
              <tbody className="text-slate-300">
                {p.components.map((c) => (
                  <tr key={c.component} className="border-t border-slate-800">
                    <td className="py-1.5">
                      {c.label}
                      {c.recurring && <span className="ml-2 rounded bg-red-900/60 px-1.5 text-xs text-red-200">lặp lại</span>}
                    </td>
                    <td>{c.count}</td>
                    <td>{pct(c.share)}</td>
                    <td>{c.recent_mistakes}</td>
                    <td className={c.direction === "worsening" ? "text-red-300" : c.direction === "improving" ? "text-emerald-300" : "text-slate-500"}>{DIRECTION[c.direction]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </Card>

      <Card title="Lỗi gần đây">
        <ErrorText error={list.error} />
        {list.data &&
          (list.data.items.length ? (
            <ul className="space-y-2 text-sm">
              {list.data.items.map((m) => (
                <li key={m.id} className="border-t border-slate-800 pt-2 first:border-0 first:pt-0">
                  <span className="text-xs text-slate-500">{new Date(m.created_at).toLocaleString("vi-VN")} · nước {m.move_number}</span>
                  <p className="text-slate-300">{m.description}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">Chưa có lỗi tư duy nào được ghi.</p>
          ))}
      </Card>
    </div>
  );
}
