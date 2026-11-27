import { useEffect, useRef, useState, type ReactNode } from "react";
import type { SessionState } from "../hooks/useSession";
import { api, errorText } from "../services/backend";
import { buildMoveReview, evalText, fromEvaluation, movePoints } from "../services/moveReview";
import type { MoveOut } from "../types/api";
import type { EngineAnalysis, MoveExplanation, MoveReview, SelfAssessment } from "../types/moveReview";

const SKIPPED: SelfAssessment = { intention: "", predicted_opponent_reply: "", predicted_variations: [], depth: null, recognized_risks: null, position_assessment: null, skipped: true };
const SHOWN = 5;

/**
 * Evaluates every newly recorded move of the player with Pikafish and saves it as a review (self-assessment skipped,
 * so the thinking score stays "no data"). Moves already reviewed are never evaluated again.
 */
export function LiveReview({ s }: { s: SessionState }) {
  const [on, setOn] = useState(true);
  const [ready, setReady] = useState(false); // reviews already stored for this session are known
  const [reviews, setReviews] = useState<MoveReview[]>([]); // newest first
  const [working, setWorking] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const done = useRef(new Map<number, string>()); // move_number -> uci reviewed or queued
  const queue = useRef(Promise.resolve());
  const session = s.session;
  const id = session?.id ?? null;
  const current = useRef(id);
  current.current = id;

  useEffect(() => {
    done.current = new Map();
    setReady(false);
    setReviews([]);
    setError(null);
    if (!id) return;
    let stale = false;
    api.listReviews(id).then(
      (xs) => {
        if (stale) return;
        done.current = new Map(xs.map((r) => [r.move_number, r.review.player_move]));
        setReady(true);
      },
      (e) => !stale && setError(errorText(e)),
    );
    return () => {
      stale = true;
    };
  }, [id]);

  async function review(sid: string, m: MoveOut) {
    if (current.current !== sid) return;
    setWorking(m.move_number);
    try {
      const ev = await api.evaluateMove(m.fen_before, m.uci);
      const r = buildMoveReview(sid, { move_number: m.move_number, board_before: m.fen_before, board_after: m.fen_after, player_move: m.uci, engine: fromEvaluation(ev) }, SKIPPED);
      await api.saveReview(sid, r);
      if (current.current !== sid) return;
      setReviews((xs) => [r, ...xs.filter((x) => x.move_number !== r.move_number)].slice(0, SHOWN));
      setError(null);
    } catch (e) {
      if (current.current !== sid) return;
      done.current.delete(m.move_number); // retried when the next move arrives
      setError(`Chưa đánh giá được nước ${m.move_number}: ${errorText(e)}`);
    } finally {
      setWorking(null);
    }
  }

  useEffect(() => {
    if (!on || !ready || !session) return;
    for (const n of [...done.current.keys()]) if (n > session.move_count) done.current.delete(n); // undone moves
    for (const m of session.moves) {
      if (m.side !== s.playerSide || done.current.get(m.move_number) === m.uci) continue;
      done.current.set(m.move_number, m.uci);
      queue.current = queue.current.then(() => review(session.id, m)); // one at a time, in move order
    }
  }, [on, ready, session, s.playerSide]);

  // Hide reviews of moves that were undone (or replaced by another move).
  const played = new Map(session?.moves.map((m) => [m.move_number, m.uci]));
  const visible = reviews.filter((r) => played.get(r.move_number) === r.player_move);

  return (
    <section className="space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Đánh giá nước đi của bạn</h2>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} />
          Tự động đánh giá sau mỗi nước
        </label>
      </div>
      <p className="text-xs text-slate-500">
        Muốn được chấm cả điểm tư duy thì tắt ô này rồi tự đánh giá từng nước ở trang Move Review (nước đã được đánh giá tự động sẽ không hiện ở đó nữa).
      </p>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {working !== null && <p className="text-sm text-slate-400">Đang phân tích nước {working} bằng Pikafish…</p>}
      {!session ? (
        <p className="text-sm text-slate-500">Chưa có buổi tập.</p>
      ) : visible.length === 0 && working === null ? (
        <p className="text-sm text-slate-500">Chưa có nước nào của bạn được đánh giá trong lần mở này.</p>
      ) : (
        <ul className="space-y-3">
          {visible.map((r) => <ReviewItem key={`${r.move_number}-${r.player_move}`} r={r} />)}
        </ul>
      )}
    </section>
  );
}

function ReviewItem({ r }: { r: MoveReview }) {
  const e = r.engine;
  const p = e ? movePoints(e, r.player_move) : null;
  const score = r.move_quality_score;
  const color = score === null ? "text-slate-400" : score >= 80 ? "text-emerald-300" : score >= 50 ? "text-amber-300" : "text-red-300";
  return (
    <li className="rounded-md border border-slate-800 p-3 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="font-medium text-slate-200">Nước {r.move_number}: <span className="font-mono">{r.player_move}</span></span>
        <span className={`font-semibold ${color}`}>{score ?? "—"}/100 · {r.move_quality_label}</span>
        {e && <span className="text-xs text-slate-500">Thế cờ {evalText(e.eval_before_cp, e.eval_before_mate)} → {evalText(e.eval_after_cp, e.eval_after_mate)}</span>}
      </div>
      {e?.explanation && <Explain e={e} x={e.explanation} />}
      {p && (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <List title="Ưu điểm" items={p.pros} cls="text-emerald-200" />
          <List title="Nhược điểm" items={p.cons} cls="text-amber-200" />
        </div>
      )}
    </li>
  );
}

const why = (rs: string[]) => (rs.length ? ` (${rs.join(", ")})` : "");

/** Best move and why, the opponent's reply and intent: all facts from the backend (rules + Pikafish). */
function Explain({ e, x }: { e: EngineAnalysis; x: MoveExplanation }) {
  const same = x.player_move === x.best_move;
  const loss = e.cp_loss ?? 0;
  return (
    <dl className="mt-2 space-y-1 text-slate-300">
      <Row label="Bạn đi">{x.player_move}{why(x.player_reasons)}</Row>
      {!same && (
        <Row label="Nước tốt nhất">
          <span className="font-medium text-emerald-200">{x.best_move}</span>
          {x.best_reasons.length ? why(x.best_reasons) : " (nước phát triển/củng cố, lợi ích nằm ở thế cờ về sau)"}
          {" "}— engine đánh giá {evalText(e.eval_before_cp, e.eval_before_mate)}, còn sau nước của bạn là {evalText(e.eval_after_cp, e.eval_after_mate)}.
        </Row>
      )}
      {x.opponent_reply && (
        <Row label={!same && loss > 50 && x.opponent_reply_reasons.length ? "Vì sao nước của bạn kém" : "Đối thủ nên đáp"}>
          {!same && loss > 50 && x.opponent_reply_reasons.length ? "đối thủ đáp " : ""}{x.opponent_reply}{why(x.opponent_reply_reasons)}
        </Row>
      )}
      {x.opponent_intent && (
        <Row label="Ý đồ đối thủ">
          muốn đi {x.opponent_intent}{x.opponent_intent_reasons.length ? why(x.opponent_intent_reasons) : " (chưa có đe dọa trực tiếp)"}
          {x.intent_handled === true && <span className="text-emerald-300"> — bạn đã hóa giải.</span>}
          {x.intent_handled === false && <span className="text-amber-300"> — nước của bạn chưa hóa giải đe dọa này.</span>}
        </Row>
      )}
      {x.best_line.length > 1 && <Row label="Biến chính (engine)">{x.best_line.join(" → ")}</Row>}
    </dl>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="inline text-xs font-semibold uppercase text-slate-500">{label}: </dt>
      <dd className="inline">{children}</dd>
    </div>
  );
}

function List({ title, items, cls }: { title: string; items: string[]; cls: string }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase text-slate-500">{title}</p>
      {items.length ? <ul className={`list-disc pl-5 ${cls}`}>{items.map((t) => <li key={t}>{t}</li>)}</ul> : <p className="text-slate-500">Không có.</p>}
    </div>
  );
}
