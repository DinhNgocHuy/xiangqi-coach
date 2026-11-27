import { useState } from "react";
import type { SessionState } from "../hooks/useSession";
import { START_FEN } from "../services/board";
import type { Side } from "../types/api";

const SIDE: Record<Side, string> = { w: "Đỏ", b: "Đen" };
const STATUS = { active: "Đang diễn ra", ended: "Đã kết thúc", checkmate: "Chiếu hết", stalemate: "Hết nước đi" } as const;
const btn = "rounded-md px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40";
const input = "rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100";

/** Create / end a training session, choose the player's side, undo, move list. */
export function SessionPanel({ s, defaultSide }: { s: SessionState; defaultSide: Side }) {
  const [custom, setCustom] = useState(false);
  const [fen, setFen] = useState("");
  const [toMove, setToMove] = useState<Side>("w");
  const [side, setSide] = useState<Side | null>(null); // null = follow vision orientation
  const session = s.session;

  function create() {
    // Only the placement field is taken from the input; side to move comes from the selector.
    const start = custom ? `${fen.trim().split(/\s+/)[0]} ${toMove} - - 0 1` : START_FEN;
    s.create(start, side ?? defaultSide);
  }

  return (
    <section className="space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Buổi tập</h2>
      {s.error && <p role="alert" className="text-sm text-red-300">{s.error}</p>}

      {session ? (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-slate-300">{STATUS[session.status]} · {session.move_count} nước · lượt: {SIDE[session.side_to_move]}</span>
            <label className="flex items-center gap-1 text-slate-400">
              Bạn cầm quân
              <select value={s.playerSide} onChange={(e) => s.setPlayerSide(e.target.value as Side)} className={input}>
                <option value="w">Đỏ</option>
                <option value="b">Đen</option>
              </select>
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={s.undo} disabled={s.busy || !session.move_count} className={`${btn} bg-slate-700 hover:bg-slate-600`}>Hoàn tác nước cuối</button>
            <button onClick={s.end} disabled={s.busy || session.status !== "active"} className={`${btn} bg-red-700 hover:bg-red-600`}>Kết thúc buổi tập</button>
            <button onClick={s.close} disabled={s.busy} className={`${btn} bg-slate-800 hover:bg-slate-700`}>Bắt đầu buổi mới</button>
          </div>
          {session.moves.length ? (
            <ol className="flex max-h-40 flex-wrap gap-x-3 gap-y-1 overflow-y-auto font-mono text-xs text-slate-300">
              {session.moves.map((m) => (
                <li key={m.move_number}>
                  <span className="text-slate-500">{m.move_number}.</span> <span className={m.side === "w" ? "text-red-300" : "text-slate-200"}>{m.uci}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-xs text-slate-500">Chưa có nước nào được ghi.</p>
          )}
        </>
      ) : (
        <div className="space-y-2 text-sm text-slate-300">
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-1"><input type="radio" name="session-start" checked={!custom} onChange={() => setCustom(false)} /> Thế cờ ban đầu</label>
            <label className="flex items-center gap-1"><input type="radio" name="session-start" checked={custom} onChange={() => setCustom(true)} /> Thế cờ tùy chỉnh (FEN)</label>
          </div>
          {custom && (
            <div className="flex flex-wrap items-center gap-2">
              <input value={fen} onChange={(e) => setFen(e.target.value)} placeholder="rnbakabnr/9/1c5c1/…" aria-label="FEN" className={`${input} w-96 font-mono`} />
              <label className="flex items-center gap-1">
                Lượt đi
                <select value={toMove} onChange={(e) => setToMove(e.target.value as Side)} className={input}>
                  <option value="w">Đỏ</option>
                  <option value="b">Đen</option>
                </select>
              </label>
            </div>
          )}
          <label className="flex items-center gap-1">
            Bạn cầm quân
            <select value={side ?? defaultSide} onChange={(e) => setSide(e.target.value as Side)} className={input}>
              <option value="w">Đỏ</option>
              <option value="b">Đen</option>
            </select>
            <span className="text-xs text-slate-500">(mặc định: bên ở phía dưới màn hình)</span>
          </label>
          <button onClick={create} disabled={s.busy || (custom && !fen.trim())} className={`${btn} bg-emerald-600 hover:bg-emerald-500`}>Tạo buổi tập</button>
        </div>
      )}
    </section>
  );
}
