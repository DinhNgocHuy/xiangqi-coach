import { useState } from "react";
import { PIECES, setSquare, squareName } from "../services/board";
import type { Placement, Square } from "../types/api";

const RED = ["K", "A", "B", "N", "R", "C", "P"];
const BLACK = RED.map((p) => p.toLowerCase());
const RANKS = [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]; // Red always shown at the bottom

/**
 * Lets the user fix a recognised board before it is recorded. Uncertain squares are outlined in amber;
 * nothing is sent until "Xác nhận thế cờ". Without onConfirm it is a read-only board view.
 */
export function BoardEditor({ initial, uncertain = [], busy, onConfirm }: {
  initial: Placement;
  uncertain?: string[];
  busy?: boolean;
  onConfirm?: (board: Placement) => void;
}) {
  const [board, setBoard] = useState(initial);
  const [sel, setSel] = useState<{ rank: number; file: number } | null>(null);
  const doubt = new Set(uncertain);

  function put(piece: Square) {
    if (!sel) return;
    setBoard((b) => setSquare(b, sel.rank, sel.file, piece));
    setSel(null);
  }

  return (
    <div className="space-y-3">
      <div className="inline-grid grid-cols-9 gap-0.5 rounded bg-amber-950/40 p-1" role="group" aria-label={onConfirm ? "Bàn cờ chỉnh sửa" : "Bàn cờ"}>
        {RANKS.map((rank) =>
          board[rank].map((sq, file) => {
            const name = squareName(rank, file);
            const active = sel?.rank === rank && sel.file === file;
            return (
              <button
                key={name}
                type="button"
                disabled={!onConfirm}
                onClick={() => setSel(active ? null : { rank, file })}
                title={`${name}${sq ? ` — ${PIECES[sq].vi}` : ""}${doubt.has(name) ? " (chưa chắc chắn)" : ""}`}
                aria-label={`${name} ${sq ? `${sq === sq.toUpperCase() ? "Đỏ" : "Đen"} ${PIECES[sq].vi}` : "trống"}`}
                aria-pressed={active}
                className={`flex h-9 w-9 items-center justify-center rounded text-lg ${rank === 5 ? "mt-1" : ""} ${
                  active ? "ring-2 ring-emerald-400" : doubt.has(name) ? "ring-2 ring-amber-400" : ""
                } ${sq ? (sq === sq.toUpperCase() ? "bg-slate-100 text-red-600" : "bg-slate-100 text-slate-900") : "bg-slate-800/60 text-slate-600 hover:bg-slate-700"}`}
              >
                {sq ? PIECES[sq].zh : "·"}
              </button>
            );
          }),
        )}
      </div>
      <p className="text-xs text-slate-500">Cột a–i từ trái sang, hàng 0 (Đỏ) ở dưới.{onConfirm && " Ô viền vàng = nhận diện chưa chắc chắn."}</p>

      {sel && (
        <div className="space-y-2 rounded border border-slate-700 p-2" aria-label={`Chọn quân cho ô ${squareName(sel.rank, sel.file)}`}>
          <p className="text-xs text-slate-400">Ô {squareName(sel.rank, sel.file)}: chọn quân</p>
          {[RED, BLACK].map((set) => (
            <div key={set[0]} className="flex flex-wrap gap-1">
              {set.map((p) => (
                <button key={p} type="button" onClick={() => put(p)}
                  className={`rounded bg-slate-100 px-2 py-1 text-sm ${p === p.toUpperCase() ? "text-red-600" : "text-slate-900"}`}>
                  {PIECES[p].zh} {PIECES[p].vi}
                </button>
              ))}
            </div>
          ))}
          <button type="button" onClick={() => put(null)} className="rounded bg-slate-700 px-2 py-1 text-sm text-white">Ô trống</button>
        </div>
      )}

      {onConfirm && (
        <button type="button" disabled={busy} onClick={() => onConfirm(board)}
          className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-40">
          Xác nhận thế cờ
        </button>
      )}
    </div>
  );
}
