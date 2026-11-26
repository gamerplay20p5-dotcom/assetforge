import { useQuery } from "@tanstack/react-query";

const KEY = "assetforge.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}
export function setToken(t: string | null): void {
  try {
    if (t) localStorage.setItem(KEY, t);
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable (private mode) — session lasts until reload */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detailText(d: unknown): string {
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`).join("; ");
  return JSON.stringify(d);
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`/api/v1${path}`, { ...init, headers, body });
  if (res.status === 401) {
    setToken(null);
    window.dispatchEvent(new Event("assetforge:logout"));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      msg = detailText((await res.json()).detail ?? msg);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Short-lived token for <img>, <a download>, WebGL loaders and EventSource (which cannot send headers). */
export function useDownloadToken(): string | undefined {
  const q = useQuery({
    queryKey: ["download-token"],
    queryFn: () => api<{ token: string; expires_in: number }>("/auth/download-token", { method: "POST" }),
    staleTime: 4 * 60 * 1000,
    refetchInterval: 4 * 60 * 1000,
    enabled: !!getToken(),
  });
  return q.data?.token;
}

export function fileUrl(assetId: string, path: string, token: string | undefined, version?: number, download = false): string {
  const p = new URLSearchParams();
  if (token) p.set("token", token);
  if (version) p.set("version", String(version));
  if (download) p.set("download", "true");
  return `/api/v1/assets/${assetId}/files/${path}?${p.toString()}`;
}

export function packageUrl(assetId: string, token: string | undefined, version?: number): string {
  const p = new URLSearchParams();
  if (token) p.set("token", token);
  if (version) p.set("version", String(version));
  return `/api/v1/assets/${assetId}/package?${p.toString()}`;
}
