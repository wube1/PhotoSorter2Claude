import type { AppState, Card } from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: {
      "X-PhotoSorter": "1",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(detail || `HTTP ${res.status}`, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  state: () => request<AppState>("GET", "/api/state"),
  scan: () => request<{ started: boolean }>("POST", "/api/scan"),
  setFolder: (ids: number[], folder: string | null) =>
    request<{ cards: Card[] }>("POST", "/api/cards/folder", { ids, folder }),
  approve: (ids: number[], approved = true) =>
    request<{ cards: Card[] }>("POST", "/api/cards/approve", { ids, approved }),
  reset: (ids: number[]) => request<{ cards: Card[] }>("POST", "/api/cards/reset", { ids }),
  addReplacement: (from_folder: string, to_folder: string) =>
    request<{ id: number }>("POST", "/api/replacements", { from_folder, to_folder }),
  deleteReplacement: (id: number) => request<{ ok: boolean }>("DELETE", `/api/replacements/${id}`),
  move: (ids: number[] | null) => request<{ started: boolean }>("POST", "/api/move", { ids }),
  remove: (ids: number[]) => request<{ started: boolean }>("POST", "/api/delete", { ids, confirm: "DELETE" }),
};
