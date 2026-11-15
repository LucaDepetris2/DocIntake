// Small presentational building blocks shared by every page.
import type { ReactNode } from "react";
import type { Status } from "../api/types";
import { label, percent } from "../lib/format";
import type { ApiState } from "../lib/useApi";

const STATUS_TONE: Record<Status, "ok" | "warn" | "bad" | "info"> = {
  received: "info",
  text_extracted: "info",
  classified: "info",
  entities_extracted: "info",
  matched: "info",
  filed: "ok",
  needs_review: "warn",
  failed: "bad",
};

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge badge-${STATUS_TONE[status]}`}>{label(status)}</span>;
}

export function Confidence({ value }: { value: number | null }) {
  const tone = value == null ? "" : value >= 0.85 ? "ok" : value >= 0.6 ? "warn" : "bad";
  return <span className={`confidence ${tone}`}>{percent(value)}</span>;
}

export function ErrorText({ error }: { error: string | null }) {
  return error ? <p className="error">{error}</p> : null;
}

/** Renders loading / error states, then `children(data)`. */
export function Async<T>({
  state,
  children,
}: {
  state: ApiState<T>;
  children: (data: T) => ReactNode;
}) {
  if (state.error) return <ErrorText error={state.error} />;
  if (state.data === null) return <p className="muted">Loading…</p>;
  return <>{children(state.data)}</>;
}

/** A definition list: [label, value] pairs. */
export function Fields({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="fields">
      {items.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Card({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      <header>
        <h2>{title}</h2>
        {actions}
      </header>
      {children}
    </section>
  );
}

/** Pill-style single choice (status filters, etc.). */
export function Tabs<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <nav className="tabs">
      {options.map((o) => (
        <button
          key={o.value}
          className={o.value === value ? "active" : ""}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </nav>
  );
}
