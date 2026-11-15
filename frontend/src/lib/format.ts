/** "discovery_request" -> "Discovery request" */
export const label = (value: string | null | undefined): string =>
  value ? value.charAt(0).toUpperCase() + value.slice(1).replaceAll("_", " ") : "—";

export const percent = (value: number | null | undefined): string =>
  value == null ? "—" : `${Math.round(value * 100)}%`;

export const dateTime = (iso: string): string =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export const day = (iso: string): string =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { dateStyle: "medium" });

export const daysUntil = (iso: string): number =>
  Math.ceil((new Date(`${iso}T00:00:00`).getTime() - Date.now()) / 86_400_000);
