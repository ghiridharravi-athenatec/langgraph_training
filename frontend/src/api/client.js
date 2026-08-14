import axios from "axios";

// Relative path works when the frontend and API share an origin (local `vite
// dev` proxy, or the docker-compose nginx frontend proxying /api/ to the
// backend container). A split deployment - this app on Vercel, the API on a
// different host/Space - needs an absolute URL instead; set VITE_API_BASE_URL
// at build time for that case.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "/api/v1",
  withCredentials: true,
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

export default api;
