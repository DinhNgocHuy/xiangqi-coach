import { useEffect, useRef, useState, type RefObject } from "react";
import type { SessionState } from "../hooks/useSession";
import { INITIAL_STABILITY, observeFrame } from "../services/autoMonitor";
import { BackendError, Cancelled, api, errorText } from "../services/backend";
import { START_FEN, START_PLACEMENT } from "../services/board";
import { grabFrameBlob } from "../services/screenCapture";
import type { BoardResult, Orientation, Placement, PositionResult } from "../types/api";
import { BoardEditor } from "./BoardEditor";

export const AUTO_INTERVAL_MS = 800; // a bot replies within ~1 s; recognition takes ~200 ms
const btn = "rounded-md px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40";
const RESULT = { recorded: "Đã ghi nước đi", unchanged: "Thế cờ không đổi", inconsistent: "Không khớp với ván đang theo dõi" } as const;
const NEED_START = "Chưa hiệu chỉnh quân cờ: hãy mở một ván mới (thế cờ ban đầu, đủ 32 quân), app sẽ tự hiệu chỉnh.";
const ORIENT: Record<Orientation, string> = { red_bottom: "Đỏ ở dưới", red_top: "Đen ở dưới" };

/** Calibrate, recognise, auto-track and confirm positions. Frames go to the local backend only, in memory. */
export function TrackingPanel({ videoRef, sharing, s, onOrientation }: {
  videoRef: RefObject<HTMLVideoElement | null>;
  sharing: boolean;
  s: SessionState;
  onOrientation: (o: Orientation) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(true); // on by default: it waits for sharing and a starting position by itself
  const [board, setBoard] = useState<BoardResult | null>(null);
  const [version, setVersion] = useState(0); // remounts the editor on each new recognition
  // The session id is kept with the result so a suggestion is never confirmed into another session.
  const [result, setResult] = useState<{ sessionId: string; r: PositionResult } | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const stability = useRef(INITIAL_STABILITY);
  const latest = useRef({ s, onOrientation });
  latest.current = { s, onOrientation };

  const currentId = s.session?.id ?? null;
  const sessionId = s.session?.status === "active" ? currentId : null;

  // A different (or no) session: nothing from the previous one may be shown or confirmed.
  useEffect(() => {
    setResult(null);
    setBoard(null);
    setInfo(null);
    setError(null);
    stability.current = INITIAL_STABILITY;
  }, [currentId]);

  async function grab(): Promise<Blob> {
    if (!videoRef.current) throw new Error("Chưa có hình ảnh từ nguồn chia sẻ.");
    return (await grabFrameBlob(videoRef.current)).blob;
  }

  function showBoard(r: BoardResult) {
    setBoard(r);
    setVersion((v) => v + 1);
    if (r.orientation) latest.current.onOrientation(r.orientation);
  }

  async function submit(pos: { fen_placement: string } | { placement: Placement }, signal?: AbortSignal, auto = false) {
    const id = latest.current.s.session?.id;
    if (!id) throw new Error("Hãy tạo buổi tập trước khi ghi thế cờ.");
    const r = await api.submitPosition(id, pos, signal);
    if (signal?.aborted) return;
    if (auto && r.result === "inconsistent" && r.suggestion) {
      // A fast opponent (a bot) replied between two frames. The backend only suggests a line when it is the
      // unique legal 2-ply match, so auto mode records it. A failure mid-way self-heals: the next frame is 1 ply.
      for (const uci of r.suggestion) await api.addMove(id, uci);
      setResult(null);
      setInfo(`Đã ghi 2 nước: ${r.suggestion.join(" ")}`);
      await latest.current.s.refresh();
      return;
    }
    if (auto && r.result === "inconsistent" && "fen_placement" in pos) return resync(id, pos.fen_placement);
    setResult({ sessionId: id, r });
    if (r.result === "recorded") await latest.current.s.refresh();
  }

  /**
   * Auto mode lost the game (a new game was started, or several plies happened between two frames): end the old
   * session (its moves stay saved) and follow on from the board as seen. ponytail: mid-game, the side to move is
   * guessed as the player's (a bot replies at once); a wrong guess self-heals at the next inconsistent position.
   */
  async function resync(oldId: string, placement: string) {
    const cur = latest.current.s;
    const fresh = placement === START_PLACEMENT;
    await api.endSession(oldId).catch(() => undefined); // a failure only leaves the old session marked active
    await cur.create(fresh ? START_FEN : `${placement} ${cur.playerSide} - - 0 1`, cur.playerSide);
    setResult(null);
    setInfo(fresh ? "Phát hiện ván mới: đã tạo buổi tập mới." : "Mất dấu ván cờ (có nước bị bỏ lỡ): đã theo dõi tiếp từ thế cờ hiện tại trong một buổi tập mới.");
  }

  async function manual(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const calibrate = () => manual(async () => {
    const r = await api.calibrate(await grab());
    onOrientation(r.orientation);
    setInfo(`Đã hiệu chỉnh quân cờ (${ORIENT[r.orientation]}, ô ${r.grid.cell}px).`);
  });
  const recognize = () => manual(async () => showBoard(await api.readBoard(await grab())));
  const confirmEdit = (placement: Placement) => manual(() => submit({ placement }));
  // `busy` pauses auto-tracking (see the effect) until both plies are recorded or have failed.
  const confirmSuggestion = (sessionIdOfResult: string, line: string[]) => manual(async () => {
    if (sessionIdOfResult !== s.session?.id) throw new Error("Gợi ý thuộc buổi tập khác, đã bỏ qua.");
    const done: string[] = [];
    try {
      for (const uci of line) {
        await api.addMove(sessionIdOfResult, uci); // both plies, in order
        done.push(uci);
      }
    } catch (e) {
      throw new Error(
        done.length
          ? `Chỉ ghi được ${done.length}/${line.length} nước (${done.join(" ")}) rồi lỗi: ${errorText(e)} Kiểm tra danh sách nước, dùng "Hoàn tác nước cuối" nếu cần.`
          : errorText(e),
      );
    } finally {
      setResult(null);
      await s.refresh();
    }
  });

  // Auto-tracking: one frame every AUTO_INTERVAL_MS, skipped while the previous request is still running.
  // Teardown (toggle off, page leave, session change, manual action) aborts the in-flight frame: it never records.
  useEffect(() => {
    if (!auto || !sharing || busy) return;
    const ctrl = new AbortController();
    const { signal } = ctrl;
    let pending = false;
    const timer = setInterval(async () => {
      if (pending || !videoRef.current) return;
      pending = true;
      try {
        const frame = await grabFrameBlob(videoRef.current);
        if (signal.aborted) return;
        let r: BoardResult;
        try {
          r = await api.readBoard(frame.blob, signal);
        } catch (e) {
          if (!(e instanceof BackendError && e.status === 409)) throw e;
          // Not calibrated yet: calibrate from this frame. Only the starting position (422 otherwise) works.
          const c = await api.calibrate(frame.blob).catch((err) => {
            if (err instanceof BackendError && err.status === 422) return null;
            throw err;
          });
          if (signal.aborted) return;
          if (!c) return setError(NEED_START);
          latest.current.onOrientation(c.orientation);
          setInfo(`Đã tự hiệu chỉnh quân cờ (${ORIENT[c.orientation]}, ô ${c.grid.cell}px).`);
          return setError(null);
        }
        if (signal.aborted) return;
        showBoard(r);
        // No active session: start one as soon as the board shows the starting position (a new game).
        const cur = latest.current.s;
        if (cur.session?.status !== "active") {
          if (r.fen_placement === START_PLACEMENT && !cur.busy) await cur.create(START_FEN, r.orientation === "red_top" ? "b" : "w");
          return;
        }
        const step = observeFrame(stability.current, r);
        stability.current = step.state;
        if (step.submit) {
          try {
            await submit({ fen_placement: step.submit }, signal, true);
          } catch (e) {
            stability.current = { ...stability.current, submitted: null }; // retry this position next frame
            throw e;
          }
        }
        if (!signal.aborted) setError(null);
      } catch (e) {
        if (signal.aborted || e instanceof Cancelled) return;
        setError(errorText(e));
        // Not calibrated / backend down: every next frame would fail the same way.
        if (e instanceof BackendError && (e.status === null || e.status === 409)) setAuto(false);
      } finally {
        pending = false;
      }
    }, AUTO_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      ctrl.abort();
    };
    // Restart only when these change; callbacks are read through `latest`/refs.
  }, [auto, sharing, sessionId, busy]);

  return (
    <section className="space-y-3 rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Nhận diện & theo dõi</h2>
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={calibrate} disabled={!sharing || busy || auto} className={`${btn} bg-amber-700 hover:bg-amber-600`}>Hiệu chỉnh (thế cờ ban đầu)</button>
        <button onClick={recognize} disabled={!sharing || busy || auto} className={`${btn} bg-sky-700 hover:bg-sky-600`}>Nhận diện bàn cờ</button>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={auto} disabled={!sharing} onChange={(e) => setAuto(e.target.checked)} />
          Theo dõi tự động
        </label>
        {auto && !sessionId && <span className="text-xs text-slate-500">Đang chờ bàn cờ ở thế ban đầu để tự tạo buổi tập.</span>}
      </div>

      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {info && <p className="text-sm text-emerald-300">{info}</p>}

      {result && result.sessionId === currentId && (
        <div role="status" className={`rounded border px-3 py-2 text-sm ${result.r.result === "inconsistent" ? "border-amber-700 bg-amber-950/40 text-amber-100" : "border-slate-700 text-slate-200"}`}>
          <p className="font-medium">
            {RESULT[result.r.result]}
            {result.r.move && <span className="ml-2 font-mono">{result.r.move.move_number}. {result.r.move.uci}</span>}
          </p>
          {result.r.reason && <p className="mt-1">{result.r.reason}</p>}
          {result.r.suggestion && (
            <div className="mt-2 flex items-center gap-2">
              <span>Gợi ý: <span className="font-mono">{result.r.suggestion.join(" ")}</span></span>
              <button onClick={() => confirmSuggestion(result.sessionId, result.r.suggestion!)} disabled={busy} className={`${btn} bg-emerald-600 hover:bg-emerald-500`}>Xác nhận 2 nước</button>
              <button onClick={() => setResult(null)} className="text-xs text-slate-400 hover:text-slate-200">Bỏ qua</button>
            </div>
          )}
        </div>
      )}

      {board && (
        <div className="space-y-2 text-sm">
          <p className="text-slate-400">
            {board.orientation ? ORIENT[board.orientation] : "Không thấy Tướng trong cung (giả định Đỏ ở dưới)"} · {Math.round(board.timing_ms)} ms ·{" "}
            {board.fen_placement ? <span className="text-emerald-300">nhận diện đầy đủ</span> : <span className="text-amber-300">{board.low_confidence.length} ô chưa chắc chắn</span>}
          </p>
          {board.problems.length > 0 && (
            <ul className="list-disc pl-5 text-amber-200">{board.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          )}
          {!auto && <BoardEditor key={version} initial={board.board} uncertain={board.low_confidence} busy={busy || !s.session} onConfirm={confirmEdit} />}
        </div>
      )}
    </section>
  );
}
