import { useState } from "react";
import { api, errorText } from "../services/backend";
import type { CoachResponse } from "../types/api";
import type { MoveReview } from "../types/moveReview";

/** Optional LLM explanation of a finished review. The rule-based review above always stays visible. */
export function CoachPanel({ review }: { review: MoveReview }) {
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<CoachResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      setRes(await api.coachFeedback(review, reveal));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const f = res?.feedback;
  return (
    <section className="space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={ask} disabled={busy} className="rounded-md bg-violet-700 px-4 py-2 text-sm font-medium text-white hover:bg-violet-600 disabled:opacity-40">
          {busy ? "Đang hỏi AI Coach…" : "Nhận xét AI Coach"}
        </button>
        <label className="flex items-center gap-2 text-sm text-slate-400">
          <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />
          Cho phép nhắc nước đi của engine
        </label>
      </div>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {res && (
        <div className="space-y-2 text-sm">
          <p className="text-xs text-slate-500">
            Nguồn: {res.source === "llm" ? `AI (${res.model ?? "LLM"})` : "theo luật"}
            {res.source === "llm" && ` · bộ lọc: loại ${res.guard.removed} câu có nước lạ, ${res.guard.illegal_variations} câu có biến sai luật, cắt ${res.guard.truncated} mục`}
          </p>
          {!res.available || !f ? (
            <p className="text-amber-200">{res.reason ?? "AI Coach không khả dụng."} Nhận xét theo luật ở trên vẫn được giữ nguyên.</p>
          ) : (
            <dl className="space-y-2 text-slate-300">
              <Item label="Bạn đã làm tốt" items={f.did_well} />
              <Item label="Bạn đã bỏ lỡ" items={f.missed} />
              <Item label="Vì sao quan trọng" items={[f.why_it_matters]} />
              <Item label="Cần học" items={[f.what_to_learn]} />
              <Item label="Bài tập tiếp theo" items={[f.next_exercise]} />
              <Item label="Câu hỏi gợi mở" items={f.questions} />
            </dl>
          )}
        </div>
      )}
    </section>
  );
}

function Item({ label, items }: { label: string; items: string[] }) {
  const xs = items.filter(Boolean);
  if (!xs.length) return null;
  return (
    <div>
      <dt className="text-xs font-semibold uppercase text-slate-500">{label}</dt>
      {xs.map((t) => <dd key={t}>{t}</dd>)}
    </div>
  );
}
