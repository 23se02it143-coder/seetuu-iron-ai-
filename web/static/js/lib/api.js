// Thin fetch wrapper: JSON in, JSON out, uniform errors.
export class ApiError extends Error {
  constructor(status, code, message, fields) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields || {};
  }
}

export async function api(path, { method = "GET", body, signal } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      signal,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(0, "network", "We couldn't reach the server. Check your connection and try again.");
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    const e = data?.error || {};
    throw new ApiError(res.status, e.code || "error", e.message || "Something went wrong. Please try again.", e.fields);
  }
  return data;
}

/** Fire-and-forget funnel counter. Never throws, never blocks. */
export function track(name, extra = {}) {
  try {
    const params = new URLSearchParams(location.search);
    const body = JSON.stringify({
      name,
      path: location.pathname,
      referrer: document.referrer || "",
      utm_source: params.get("utm_source") || sessionStorage.getItem("utm_source") || "",
      ...extra,
    });
    fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => {});
  } catch { /* analytics must never break the page */ }
}
