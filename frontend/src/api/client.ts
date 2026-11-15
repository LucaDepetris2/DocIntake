// The single place that talks HTTP: adds the token, parses JSON, normalises errors.
import type { User } from "./types";

const BASE = "/api";
const TOKEN_KEY = "docintake.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};

export const session = {
  getToken: (): string | null => localStorage.getItem(TOKEN_KEY),
  setToken: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
  /** Called on any 401 (expired/invalid token): the app logs out. */
  onUnauthorized: (handler: () => void) => {
    onUnauthorized = handler;
  },
};

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = session.getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (response.ok) return response;

  if (response.status === 401) onUnauthorized();
  const body = await response.json().catch(() => null);
  const detail = body?.detail;
  const message =
    typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((d: { msg: string }) => d.msg).join("; ") // FastAPI 422
        : response.statusText;
  throw new ApiError(response.status, message);
}

const json = async <T>(path: string, init?: RequestInit): Promise<T> =>
  (await request(path, init)).json() as Promise<T>;

const send = <T>(method: string, path: string, body?: unknown): Promise<T> =>
  json<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  get: <T>(path: string) => json<T>(path),
  post: <T>(path: string, body?: unknown) => send<T>("POST", path, body),
  put: <T>(path: string, body: unknown) => send<T>("PUT", path, body),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return json<T>(path, { method: "POST", body: form });
  },
  blob: async (path: string) => (await request(path)).blob(),
  login: (email: string, password: string) =>
    json<{ access_token: string; user: User }>("/auth/token", {
      method: "POST",
      body: new URLSearchParams({ username: email, password }), // OAuth2 password form
    }),
};
