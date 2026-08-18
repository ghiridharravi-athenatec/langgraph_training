import axios from "axios";

// Relative path works when the frontend and API share an origin (local `vite
// dev` proxy, or the docker-compose nginx frontend proxying /api/ to the
// backend container). A split deployment - this app on Vercel, the API on a
// different host/Space - needs an absolute URL instead; set VITE_API_BASE_URL
// at build time for that case.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1",
  withCredentials: true,
  headers: {
    // No-op against a normal backend; skips ngrok's browser interstitial page
    // when VITE_API_BASE_URL points at a free ngrok tunnel domain, which would
    // otherwise return that page's HTML instead of the API's JSON.
    "ngrok-skip-browser-warning": "true",
  },
});

// FastAPI's `detail` is a plain string for HTTPException, but a list of
// {loc, msg, ...} objects for Pydantic 422 validation errors - stringifying
// the latter directly (`${detail}`) renders as "[object Object]".
export function formatErrorDetail(err, fallback = "Something went wrong. Please try again.") {
  const detail = err?.response?.data?.detail;
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === "string") return d;
        const field = Array.isArray(d.loc) ? d.loc.slice(1).join(".") : null;
        return field ? `${field}: ${d.msg}` : d.msg || JSON.stringify(d);
      })
      .join("; ");
  }
  return fallback;
}

let accessToken = null;
let refreshPromise = null;

export function setAccessToken(token) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

api.interceptors.request.use((request) => {
  if (accessToken) {
    request.headers.Authorization = `Bearer ${accessToken}`;
  }
  return request;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error;
    const isAuthEndpoint = config?.url?.startsWith("/auth/");

    if (response?.status === 401 && !config._retried && !isAuthEndpoint) {
      config._retried = true;
      try {
        if (!refreshPromise) {
          refreshPromise = api.post("/auth/refresh").finally(() => {
            refreshPromise = null;
          });
        }
        const { data } = await refreshPromise;
        setAccessToken(data.access_token);
        config.headers.Authorization = `Bearer ${data.access_token}`;
        return api(config);
      } catch (refreshError) {
        setAccessToken(null);
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

// Streams an SSE response from a POST endpoint - axios doesn't expose a
// progressive-read body, and the native EventSource API only supports GET, so
// this bypasses axios and talks to fetch() directly for just this one call.
// Reuses the same bearer-token/refresh-on-401 flow as the axios interceptor
// above, since none of that applies automatically outside axios.
//
// onDelta(text) is called for every {"type": "delta", "text": "..."} frame as
// it arrives; the returned promise resolves with the final {"type": "done", ...}
// payload (stripped of its "type" key) once the stream ends.
async function _fetchStream(path, body, token) {
  return fetch(`${api.defaults.baseURL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "ngrok-skip-browser-warning": "true",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
}

export async function streamChat(path, body, { onDelta } = {}) {
  let res = await _fetchStream(path, body, getAccessToken());

  if (res.status === 401) {
    const { data } = await api.post("/auth/refresh");
    setAccessToken(data.access_token);
    res = await _fetchStream(path, body, data.access_token);
  }

  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      // Response body wasn't JSON - fall through with no detail.
    }
    const err = new Error(detail || `Request failed (${res.status})`);
    err.response = { status: res.status, data: { detail } };
    throw err;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = null;

  while (true) {
    const { done: streamDone, value } = await reader.read();
    if (streamDone) break;
    buffer += decoder.decode(value, { stream: true });

    let separatorIndex;
    while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
      if (!dataLine) continue;

      const payload = JSON.parse(dataLine.slice(6));
      if (payload.type === "delta") {
        onDelta?.(payload.text);
      } else if (payload.type === "done") {
        const { type, ...rest } = payload;
        done = rest;
      }
    }
  }

  return done;
}

export default api;
