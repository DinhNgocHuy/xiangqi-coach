import { useCallback, useEffect, useState } from "react";
import { BackendError, Cancelled, api, errorText, retryWhileOffline } from "../services/backend";
import type { SessionDetail, Side } from "../types/api";

const ACTIVE_KEY = "xqc.activeSession";
const sideKey = (id: string) => `xqc.playerSide.${id}`;

/**
 * The current training session, shared by Screen Monitor and Move Review (lives in App).
 * ponytail: the backend has no player_side field, so the player's side is kept per session in localStorage;
 * move it to the sessions table when several devices/profiles must share sessions.
 */
export function useSession() {
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [playerSide, setPlayerSideState] = useState<Side>("w");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** With a signal (initial restore): retries while the backend sidecar is still starting. */
  const load = useCallback(async (id: string, signal?: AbortSignal) => {
    try {
      const s = signal ? await retryWhileOffline(() => api.getSession(id), signal) : await api.getSession(id);
      if (signal?.aborted) return;
      setSession(s);
      setPlayerSideState(localStorage.getItem(sideKey(id)) === "b" ? "b" : "w");
      setError(null);
    } catch (e) {
      if (e instanceof Cancelled || signal?.aborted) return;
      if (e instanceof BackendError && e.status === 404) localStorage.removeItem(ACTIVE_KEY); // database was reset
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    const id = localStorage.getItem(ACTIVE_KEY);
    if (!id) return;
    const ctrl = new AbortController();
    load(id, ctrl.signal);
    return () => ctrl.abort();
  }, [load]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const refresh = useCallback(async () => {
    if (session) await load(session.id);
  }, [session, load]);

  return {
    session,
    playerSide,
    error,
    busy,
    refresh,
    create: (startFen: string | undefined, side: Side) =>
      run(async () => {
        const s = await api.createSession(startFen);
        localStorage.setItem(ACTIVE_KEY, s.id);
        localStorage.setItem(sideKey(s.id), side);
        setPlayerSideState(side);
        setSession(s);
      }),
    setPlayerSide: (side: Side) => {
      if (session) localStorage.setItem(sideKey(session.id), side);
      setPlayerSideState(side);
    },
    end: () => run(async () => session && setSession(await api.endSession(session.id))),
    undo: () => run(async () => {
      if (!session) return;
      await api.undoMove(session.id);
      await load(session.id);
    }),
    /** Forget the session locally (it stays in the database and in the stats). */
    close: () => {
      localStorage.removeItem(ACTIVE_KEY);
      setSession(null);
    },
  };
}

export type SessionState = ReturnType<typeof useSession>;
