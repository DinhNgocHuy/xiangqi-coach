import { useEffect, useState } from "react";
import { api, errorText } from "../services/backend";
import type { CoachStatus, EngineStatus, Health } from "../types/api";

export const POLL_MS = 10_000;

export type BackendStatus = { health: Health | null; engine: EngineStatus | null; coach: CoachStatus | null; error: string | null; checked: boolean };

/** Polls /health, /engine/status and /coach/status. GETs only, so polling never changes data. */
export function useBackendStatus(): BackendStatus {
  const [s, setS] = useState<BackendStatus>({ health: null, engine: null, coach: null, error: null, checked: false });

  useEffect(() => {
    let alive = true;
    async function poll() {
      const [h, e, c] = await Promise.allSettled([api.health(), api.engineStatus(), api.coachStatus()]);
      if (!alive) return;
      setS({
        health: h.status === "fulfilled" ? h.value : null,
        engine: e.status === "fulfilled" ? e.value : null,
        coach: c.status === "fulfilled" ? c.value : null,
        error: h.status === "rejected" ? errorText(h.reason) : null,
        checked: true,
      });
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return s;
}
