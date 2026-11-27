import { useEffect, useState } from "react";
import type { SessionState } from "../hooks/useSession";
import { api, errorText } from "../services/backend";
import { buildMoveReview, fromEvaluation } from "../services/moveReview";
import type { MoveOut, SessionDetail, StoredReview } from "../types/api";
import type { EngineAnalysis, MoveReview, SelfAssessment } from "../types/moveReview";
import { CoachPanel } from "./CoachPanel";
import { MoveReviewCard } from "./MoveReviewCard";
import { SelfAssessmentForm } from "./SelfAssessmentForm";

const item = "w-full rounded-md px-3 py-2 text-left text-sm transition";

/** Review the player's recorded moves: self-assessment first, then Pikafish, then the stored review. */
export function SessionReview({ s, session }: { s: SessionState; session: SessionDetail }) {
  const [stored, setStored] = useState<StoredReview[]>([]);
  const [selected, setSelected] = useState<MoveOut | null>(null);
  const [shown, setShown] = useState<MoveReview | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stale = false; // a newer session/move count replaced this request
    api.listReviews(session.id).then(
      (xs) => !stale && setStored(xs),
      (e) => !stale && setError(errorText(e)),
    );
    return () => {
      stale = true;
    };
  }, [session.id, session.move_count]);

  const reviewed = new Set(stored.map((r) => r.move_number));
  const pending = session.moves.filter((m) => m.side === s.playerSide && !reviewed.has(m.move_number));

  const submit = (sa: SelfAssessment) => selected && analyze(selected, sa);
  // A saved review made while Pikafish was unavailable: evaluate again with the same answers and upsert.
  const reanalyze = (r: MoveReview) =>
    analyze({ move_number: r.move_number, fen_before: r.board_before, fen_after: r.board_after, uci: r.player_move }, r.self_assessment);

  async function analyze(move: Pick<MoveOut, "move_number" | "fen_before" | "fen_after" | "uci">, sa: SelfAssessment) {
    setBusy(true);
    setError(null);
    let engine: EngineAnalysis | null = null;
    const msgs: string[] = [];
    try {
      const ev = await api.evaluateMove(move.fen_before, move.uci);
      engine = fromEvaluation(ev);
      msgs.push(...ev.notes);
    } catch (e) {
      msgs.push(`Không phân tích được bằng Pikafish: ${errorText(e)} Nhận xét chỉ dựa trên phần tự đánh giá.`);
    }
    const review = buildMoveReview(
      session.id,
      { move_number: move.move_number, board_before: move.fen_before, board_after: move.fen_after, player_move: move.uci, engine },
      sa,
    );
    setNotes(msgs);
    setShown(review);
    setSelected(null);
    try {
      const saved = await api.saveReview(session.id, review);
      setStored((xs) => [...xs.filter((x) => x.move_number !== saved.move_number), saved].sort((a, b) => a.move_number - b.move_number));
    } catch (e) {
      setError(`Chưa lưu được nhận xét: ${errorText(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
      <aside className="space-y-6">
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <h2 className="mb-2 text-sm font-semibold text-slate-400">Nước của bạn chờ đánh giá</h2>
          {pending.length ? (
            <ul className="space-y-1">
              {pending.map((m) => (
                <li key={m.move_number}>
                  <button
                    onClick={() => { setSelected(m); setShown(null); }}
                    aria-current={selected === m ? "true" : undefined}
                    className={`${item} ${selected === m ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-800"}`}
                  >
                    Nước {m.move_number}: <span className="font-mono">{m.uci}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">Không có nước nào của bạn chờ đánh giá.</p>
          )}
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-3">
          <h2 className="mb-2 text-sm font-semibold text-slate-400">Lịch sử buổi tập</h2>
          {stored.length ? (
            <ul className="space-y-1">
              {stored.map((r) => (
                <li key={r.move_number}>
                  <button
                    onClick={() => { setShown(r.review); setSelected(null); setNotes([]); }}
                    aria-current={shown?.move_number === r.move_number ? "true" : undefined}
                    className={`${item} ${shown?.move_number === r.move_number ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-800"}`}
                  >
                    Nước {r.move_number}: <span className="font-mono">{r.review.player_move}</span>
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

      <div className="space-y-4">
        {error && <p role="alert" className="rounded-md border border-red-800 bg-red-950/60 px-4 py-3 text-sm text-red-200">{error}</p>}
        {selected ? (
          // Engine data stays hidden: Pikafish is only asked after the form is submitted or skipped.
          <section className="space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">
                Nước {selected.move_number}: <span className="font-mono">{selected.uci}</span>
              </h2>
              <p className="mt-1 break-all font-mono text-xs text-slate-500">Trước: {selected.fen_before}</p>
            </div>
            {busy ? <p className="text-sm text-slate-400">Đang phân tích bằng Pikafish…</p> : <SelfAssessmentForm key={selected.move_number} onSubmit={submit} />}
          </section>
        ) : shown ? (
          <>
            {notes.length > 0 && (
              <ul className="list-disc rounded-md border border-amber-800 bg-amber-950/40 py-2 pl-8 pr-4 text-sm text-amber-100">
                {notes.map((n) => <li key={n}>{n}</li>)}
              </ul>
            )}
            {shown.engine === null && reviewed.has(shown.move_number) && (
              <button onClick={() => reanalyze(shown)} disabled={busy} className="rounded-md bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-600 disabled:opacity-40">
                {busy ? "Đang phân tích…" : "Phân tích lại bằng engine"}
              </button>
            )}
            <MoveReviewCard review={shown} />
            <CoachPanel key={`${shown.move_number}-${shown.created_at}`} review={shown} />
          </>
        ) : (
          <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-slate-700 text-sm text-slate-500">
            {busy ? "Đang phân tích…" : "Chọn một nước đi để tự đánh giá, hoặc xem lại lịch sử buổi tập."}
          </div>
        )}
      </div>
    </div>
  );
}
