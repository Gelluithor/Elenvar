let csrfToken = "";
let unauthorizedHandler: (() => void) | null = null;

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

const FIELD_NAMES: Record<string, string> = {
  username: "Uživatelské jméno",
  password: "Heslo",
  host: "Adresa",
  name: "Název",
  http_port: "HTTP port",
  rtsp_port: "RTSP port",
  webhook_url: "URL webhooku",
  code: "Kód",
  new_password: "Nové heslo",
};

interface ValidationIssue {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}

function extractDetail(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const detail = (data as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return (detail as ValidationIssue[])
      .map((issue) => {
        const field = String(issue.loc?.[issue.loc.length - 1] ?? "");
        const label = FIELD_NAMES[field] ?? field;
        const msg = (issue.msg ?? "").replace(/^Value error, /, "");
        if (issue.type === "string_pattern_mismatch") return `${label}: neplatný formát`;
        if (issue.type === "string_too_short") return `${label}: hodnota je příliš krátká`;
        if (issue.type === "string_too_long") return `${label}: hodnota je příliš dlouhá`;
        if (issue.type?.startsWith("greater_than") || issue.type?.startsWith("less_than"))
          return `${label}: hodnota mimo povolený rozsah`;
        return label ? `${label}: ${msg}` : msg;
      })
      .join("; ");
  }
  return null;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Server není dostupný. Zkontrolujte připojení.");
  }

  let data: unknown = null;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    data = await response.json().catch(() => null);
  }
  if (!response.ok) {
    const message = extractDetail(data) ?? `Požadavek selhal (HTTP ${response.status}).`;
    if (response.status === 401 && unauthorizedHandler && !path.startsWith("/api/auth/")) {
      unauthorizedHandler();
    }
    throw new ApiError(response.status, message);
  }
  return data as T;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Neznámá chyba.";
}
