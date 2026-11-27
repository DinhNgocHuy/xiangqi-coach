import type { ReactNode } from "react";
import { NO_DATA, THINKING_WEIGHTS, evalText } from "../services/moveReview";
import type { MoveReview, ThinkingComponent } from "../types/moveReview";

const COMPONENT_LABEL: Record<ThinkingComponent, string> = {
  threatAwareness: "Nhận diện đe dọa",
  responsePrediction: "Dự đoán phản ứng đối thủ",
  variationCalculation: "Tính biến",
  positionEvaluation: "Đánh giá thế cờ",
  pieceSafety: "An toàn quân cờ",
};
const CONFIDENCE = { low: "Thấp", medium: "Trung bình", high: "Cao" } as const;

export function MoveReviewCard({ review: r }: { review: MoveReview }) {
  return (
    <article className="space-y-4">
      <Section title="A. Tổng quan">
        {r.engine?.source === "sample" && (
          <p className="mb-3 inline-block rounded bg-amber-900/60 px-2 py-1 text-xs font-medium text-amber-200">Dữ liệu mẫu — chưa qua Pikafish</p>
        )}
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Stat label="Chất lượng nước đi" value={r.move_quality_score === null ? NO_DATA : `${r.move_quality_score}/100`} sub={r.move_quality_score === null ? undefined : r.move_quality_label} />
          <Stat label="Chất lượng tư duy" value={r.thinking_quality_score === null ? NO_DATA : `${r.thinking_quality_score}/100`} />
          <Stat label="Đánh giá trước → sau" value={`${evalText(r.engine_evaluation_before, r.engine?.eval_before_mate)} → ${evalText(r.engine_evaluation_after, r.engine?.eval_after_mate)}`} />
          <Stat label="Độ tin cậy" value={CONFIDENCE[r.confidence]} />
        </dl>
      </Section>

      <Section title="B. Tư duy">
        <ul className="space-y-1 text-sm">
          {(Object.keys(THINKING_WEIGHTS) as ThinkingComponent[]).map((c) => {
            const v = r.thinking_components[c];
            return (
              <li key={c} className="flex justify-between gap-4">
                <span className="text-slate-300">
                  {COMPONENT_LABEL[c]} <span className="text-slate-500">({THINKING_WEIGHTS[c]}%)</span>
                </span>
                <span className={v === null ? "text-slate-500" : "font-medium text-slate-100"}>{v === null ? "Chưa đủ dữ liệu" : `${Math.round(v * 100)}%`}</span>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section title="C. Điểm tốt">
        <List items={r.strengths} empty="Chưa có điểm tốt được ghi nhận." />
      </Section>

      <Section title="D. Điểm chưa tốt">
        <List items={r.missed_threats} empty="Không phát hiện lỗi tư duy từ các câu bạn đã trả lời." />
      </Section>

      <Section title="E. Bài học">
        <List items={r.learning_notes} empty="—" />
        <h3 className="mt-3 text-xs font-semibold uppercase text-slate-500">Câu hỏi gợi mở</h3>
        <List items={r.guiding_questions} empty="—" />
        <p className="mt-3 text-sm">
          <span className="text-slate-500">Chủ đề luyện tập tiếp theo: </span>
          <span className="font-medium text-emerald-300">{r.next_training_topic}</span>
        </p>
      </Section>

      {r.engine && (
        <details className="rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm">
          <summary className="cursor-pointer font-medium text-slate-300">Xem phân tích engine</summary>
          <dl className="mt-3 space-y-1 font-mono text-slate-300">
            <div><dt className="inline text-slate-500">Nước tốt nhất: </dt><dd className="inline">{r.engine.best_move}</dd></div>
            <div><dt className="inline text-slate-500">Đáp trả mạnh nhất của đối thủ: </dt><dd className="inline">{r.engine.opponent_best_replies.join(", ") || "—"}</dd></div>
            <div><dt className="inline text-slate-500">Biến chính: </dt><dd className="inline">{r.engine.principal_variation.join(" ") || "—"}</dd></div>
          </dl>
        </details>
      )}
    </article>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">{title}</h2>
      {children}
    </section>
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

function List({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
      {items.map((t) => <li key={t}>{t}</li>)}
    </ul>
  );
}
