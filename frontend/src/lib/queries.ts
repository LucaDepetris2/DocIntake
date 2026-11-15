import { useMemo } from "react";
import { api } from "../api/client";
import type { Matter, Status } from "../api/types";
import { useApi } from "./useApi";

export const FINAL_STATUSES: Status[] = ["filed", "needs_review", "failed"];
export const isProcessing = (status: Status) => !FINAL_STATUSES.includes(status);

/** The firm's matters, plus a lookup by id (used to show case numbers). */
export function useMatters() {
  const state = useApi(() => api.get<Matter[]>("/matters"), []);
  const byId = useMemo(
    () => new Map((state.data ?? []).map((m) => [m.id, m])),
    [state.data],
  );
  return { matters: state.data ?? [], byId };
}
