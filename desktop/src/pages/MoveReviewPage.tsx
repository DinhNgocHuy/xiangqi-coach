import { useState } from "react";
import { MoveReviewCard } from "../components/MoveReviewCard";
import { SelfAssessmentForm } from "../components/SelfAssessmentForm";
import { SessionReview } from "../components/SessionReview";
import { SAMPLE_MOVES } from "../data/sampleMoves";
import type { SessionState } from "../hooks/useSession";
import type { MoveReview, PlayedMove, SelfAssessment } from "../types/moveReview";

const keyOf = (m: { board_before: string; player_move: string }) => `${m.board_before}|${m.player_move}`;
const item = "w-full rounded-md px-3 py-2 text-left text-sm transition";

type SampleProps = { reviews: MoveReview[]; onAddReview: (played: PlayedMove, sa: SelfAssessment) => void };

export function MoveReviewPage({ session, ...sample }: SampleProps & { session: SessionState }) {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-100">Move Review</h1>
        <p className="text-sm text-slate-400">Tự đánh giá tư duy sau mỗi nước đi trước khi xem phân tích của Pikafish.</p>
      </header>
      {session.session ? <SessionReview s={session} session={session.session} /> : <SampleReview {...sample} />}
    </div>
  );
}

/** Fallback when no session exists: hand-written sample moves, kept in memory only. */
function SampleReview({ reviews, onAddReview }: SampleProps) {
  const [selected, setSelected] = useState<PlayedMove | null>(null);
  const [shown, setShown] = useState<number | null>(null);
  const reviewed = new Set(reviews.map(keyOf));
  const pending = SAMPLE_MOVES.filter((m) => !reviewed.has(keyOf(m)));

  function submit(sa: SelfAssessment) {
    if (!selected) return;
    onAddReview(selected, sa);
    setShown(reviews.length); // index of the review the parent is appending
    setSelected(null);
  }

  return (
    <div className="space-y-6">
      <p role="note" className="rounded-md border border-amber-800 bg-amber-950/40 px-4 py-3 text-sm text-amber-100">
        <span className="font-semibold">Chế độ mẫu</span> — chưa có buổi tập nào. Các nước và dữ liệu engine dưới đây là mẫu viết tay, không qua
        Pikafish và không được lưu. Tạo buổi tập ở Screen Monitor để đánh giá nước đi thật.
      </p>

      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <aside className="space-y-6">
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <h2 className="mb-2 text-sm font-semibold text-slate-400">Nước đi chờ đánh giá</h2>
            {pending.length ? (
              <ul className="space-y-1">
                {pending.map((m) => (
                  <li key={keyOf(m)}>
                    <button
                      onClick={() => { setSelected(m); setShown(null); }}
                      aria-current={selected === m ? "true" : undefined}
                      className={`${item} ${selected === m ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-800"}`}
                    >
                      Nước {m.move_number}: <span className="font-mono">{m.player_move}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500">Đã đánh giá hết nước mẫu.</p>
            )}
          </section>

          <section className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <h2 className="mb-2 text-sm font-semibold text-slate-400">Lịch sử buổi tập</h2>
            {reviews.length ? (
              <ul className="space-y-1">
                {reviews.map((r, i) => (
                  <li key={r.created_at + i}>
                    <button
                      onClick={() => { setShown(i); setSelected(null); }}
                      aria-current={shown === i ? "true" : undefined}
                      className={`${item} ${shown === i ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-800"}`}
                    >
                      Nước {r.move_number}: <span className="font-mono">{r.player_move}</span>
                      <span className="block text-xs text-slate-500">
                        Tư duy: {r.thinking_quality_score ?? "—"} · Nước đi: {r.move_quality_score ?? "—"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500">Chưa có nước nào được đánh giá.</p>
            )}
          </section>
        </aside>

        <div>
          {selected ? (
            // Practice mode: engine data stays hidden until the form is submitted or skipped.
            <section className="space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-5">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">
                  Nước {selected.move_number}: <span className="font-mono">{selected.player_move}</span>
                </h2>
                <p className="mt-1 break-all font-mono text-xs text-slate-500">Trước: {selected.board_before}</p>
                <p className="break-all font-mono text-xs text-slate-500">Sau: {selected.board_after}</p>
              </div>
              <SelfAssessmentForm key={keyOf(selected)} onSubmit={submit} />
            </section>
          ) : shown !== null && reviews[shown] ? (
            <MoveReviewCard review={reviews[shown]} />
          ) : (
            <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-slate-700 text-sm text-slate-500">
              Chọn một nước đi để tự đánh giá, hoặc xem lại lịch sử buổi tập.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
