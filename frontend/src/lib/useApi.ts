import { useCallback, useEffect, useState } from "react";

export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Load data from the API whenever `deps` change. One hook for every page. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[]): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  const stableLoad = useCallback(load, deps);

  useEffect(() => {
    let cancelled = false; // ignore responses for stale requests
    setLoading(true);
    stableLoad()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((err: Error) => !cancelled && setError(err.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [stableLoad, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, loading, reload };
}

/** Re-run `callback` every `ms` while `active` (e.g. poll documents still processing). */
export function usePolling(callback: () => void, ms: number, active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const id = setInterval(callback, ms);
    return () => clearInterval(id);
  }, [callback, ms, active]);
}

export interface Action<A extends unknown[]> {
  run: (...args: A) => Promise<void>;
  busy: boolean;
  error: string | null;
}

/** Run a mutation (login, upload, review...) tracking busy/error state. */
export function useAction<A extends unknown[]>(fn: (...args: A) => Promise<unknown>): Action<A> {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(
    async (...args: A) => {
      setBusy(true);
      setError(null);
      try {
        await fn(...args);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [fn],
  );
  return { run, busy, error };
}
