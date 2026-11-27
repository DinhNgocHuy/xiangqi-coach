import { useCallback, useEffect, useState } from "react";
import { Cancelled, errorText, retryWhileOffline } from "../services/backend";

/** Loads one backend resource on mount (retrying while the backend is still starting); `reload` fetches it again. */
export function useLoad<T>(fetcher: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // fetcher is expected to be a stable module-level function (api.*)
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetcher());
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, [fetcher]);

  useEffect(() => {
    const ctrl = new AbortController();
    retryWhileOffline(fetcher, ctrl.signal).then(
      (d) => {
        if (ctrl.signal.aborted) return;
        setData(d);
        setError(null);
        setLoading(false);
      },
      (e) => {
        if (ctrl.signal.aborted || e instanceof Cancelled) return;
        setError(errorText(e));
        setLoading(false);
      },
    );
    return () => ctrl.abort();
  }, [fetcher]);

  return { data, error, loading, reload };
}
