export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly fieldIssues: ApiFieldIssue[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type ApiFieldIssue = {
  field: string;
  message: string;
};

export function getApiFieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  return Object.fromEntries(
    error.fieldIssues.map(({ field, message }) => [field, message]),
  );
}

let csrfToken = "";
let refreshInFlight: Promise<boolean> | null = null;
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/+$/, "");

function apiUrl(path: string): string {
  const apiPath = path.startsWith("/api/v1") ? path.slice("/api/v1".length) : path;
  return `${API_BASE_URL}${apiPath}`;
}

export async function initializeCsrfToken(): Promise<void> {
  const response = await fetch(apiUrl("/api/v1/auth/csrf"), {
    credentials: "include",
  });
  if (!response.ok) {
    throw new ApiError(`Could not initialize request security (${response.status}).`, response.status);
  }
  const result: unknown = await response.json();
  if (
    typeof result !== "object" ||
    result === null ||
    !("csrf_token" in result) ||
    typeof result.csrf_token !== "string"
  ) {
    throw new ApiError("The server returned an invalid CSRF token.", response.status);
  }
  csrfToken = result.csrf_token;
}

function isMutating(method: string): boolean {
  return !["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
}

async function send(
  path: string,
  init: RequestInit,
): Promise<Response> {
  const method = init.method ?? "GET";
  if (isMutating(method) && !csrfToken) {
    await initializeCsrfToken();
  }
  const headers = new Headers(init.headers);
  if (isMutating(method)) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  return fetch(apiUrl(path), {
    ...init,
    headers,
    credentials: "include",
  });
}

async function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await send("/api/v1/auth/refresh", { method: "POST" });
        return response.ok;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

export async function apiRequest(
  path: string,
  init: RequestInit = {},
  refreshOnUnauthorized = true,
): Promise<Response> {
  const response = await send(path, init);
  if (
    response.status === 401 &&
    refreshOnUnauthorized &&
    path !== "/api/v1/auth/refresh" &&
    path !== "/api/v1/auth/login" &&
    path !== "/api/v1/auth/register"
  ) {
    if (await refreshSession()) {
      return send(path, init);
    }
  }
  return response;
}

type UploadResult = {
  status: number;
  body: unknown;
};

function sendFormData(
  path: string,
  method: "POST" | "PUT",
  formData: FormData,
  onProgress: (progress: number) => void,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, apiUrl(path));
    xhr.withCredentials = true;
    xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.min(99, Math.floor((event.loaded / event.total) * 100)));
      }
    };
    xhr.onload = () => {
      let body: unknown;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : undefined;
      } catch {
        body = undefined;
      }
      resolve({ status: xhr.status, body });
    };
    xhr.onerror = () => reject(new ApiError("The resource upload failed to connect.", 0));
    xhr.onabort = () => reject(new ApiError("The resource upload was canceled.", 0));
    xhr.send(formData);
  });
}

export async function uploadFormData(
  path: string,
  method: "POST" | "PUT",
  formData: FormData,
  onProgress: (progress: number) => void,
  fallback = "Could not upload the resource file.",
): Promise<unknown> {
  if (!csrfToken) {
    await initializeCsrfToken();
  }
  let result = await sendFormData(path, method, formData, onProgress);
  if (result.status === 401 && path !== "/api/v1/auth/refresh") {
    if (await refreshSession()) {
      result = await sendFormData(path, method, formData, onProgress);
    }
  }
  if (result.status < 200 || result.status >= 300) {
    throw responseErrorFromResult({ status: result.status }, result.body, fallback);
  }
  onProgress(100);
  return result.body;
}

export async function requestJson(
  path: string,
  init: RequestInit = {},
  fallback = "The request failed.",
  refreshOnUnauthorized = true,
): Promise<unknown> {
  const response = await apiRequest(path, init, refreshOnUnauthorized);
  const result: unknown = response.status === 204 ? undefined : await response.json();
  if (!response.ok) {
    throw responseErrorFromResult(response, result, fallback);
  }
  return result;
}

function responseErrorFromResult(
  response: Pick<Response, "status">,
  result: unknown,
  fallback: string,
): ApiError {
  const rawDetail =
    typeof result === "object" &&
    result !== null &&
    "detail" in result
      ? result.detail
      : undefined;
  const issues =
    Array.isArray(rawDetail)
      ? rawDetail.flatMap((issue: unknown): ApiFieldIssue[] => {
          if (typeof issue !== "object" || issue === null || !("msg" in issue)) {
            return [];
          }
          const message = issue.msg;
          if (typeof message !== "string") return [];
          const location =
            "loc" in issue && Array.isArray(issue.loc)
              ? issue.loc.filter(
                  (part): part is string | number =>
                    typeof part === "string" || typeof part === "number",
                )
              : [];
          const field = location
            .filter(
              (part) =>
                !["body", "query", "path", "metadata"].includes(String(part)),
            )
            .map(String)
            .join(".");
          return [{ field, message }];
        })
      : [];
  const detail =
    typeof rawDetail === "string"
      ? rawDetail
      : issues
          .map(({ field, message }) =>
            field ? `${field}: ${message}` : message,
          )
          .join(" ");
  return new ApiError(detail || fallback, response.status, issues);
}

export function clearCsrfToken(): void {
  csrfToken = "";
}
