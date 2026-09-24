// Cliente HTTP de la API: token JWT, errores legibles y manejo de sesión expirada (401).
const BASE_URL = "/api";
const TOKEN_KEY = "xlive_token";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let onUnauthorized = null;

// AuthProvider registra aquí qué hacer cuando la API responde 401 con una sesión activa.
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler;
}

// localStorage puede fallar (modo privado, datos bloqueados): la app sigue sin persistir la sesión.
export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch (err) {
    console.error("[api.client.setToken] No se pudo guardar la sesión:", err);
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch (err) {
    console.error("[api.client.clearToken] No se pudo borrar la sesión:", err);
  }
}

// FastAPI responde `detail` como texto, o como lista de errores de validación (422).
export function messageFromDetail(detail, status) {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((e) => {
        const campo = (e.loc || []).filter((p) => p !== "body").join(".");
        return campo ? `${campo}: ${e.msg}` : e.msg;
      })
      .join("; ");
  }
  return `Error HTTP ${status}`;
}

function buildUrl(path, params) {
  const query = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.append(key, String(value));
  });
  const qs = query.toString();
  return `${BASE_URL}${path}${qs ? `?${qs}` : ""}`;
}

export async function request(path, { method = "GET", body, params, auth = true } = {}) {
  const headers = {};
  const token = auth ? getToken() : null;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res;
  try {
    res = await fetch(buildUrl(path, params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    console.error(`[api.client.request] Falló la conexión (${method} ${path}):`, err);
    throw new ApiError("No se pudo conectar con el servidor", 0);
  }

  if (res.status === 204) return null;

  let data = null;
  try {
    data = await res.json();
  } catch {
    // Respuesta sin JSON: se usa el mensaje genérico por código HTTP.
  }

  if (!res.ok) {
    if (res.status === 401 && token) {
      clearToken();
      if (onUnauthorized) onUnauthorized();
    }
    const message = messageFromDetail(data?.detail, res.status);
    console.error(`[api.client.request] ${method} ${path} → ${res.status}: ${message}`);
    throw new ApiError(message, res.status);
  }
  return data;
}

export const api = {
  get: (path, params) => request(path, { params }),
  post: (path, body) => request(path, { method: "POST", body }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  // Los borrados de la API exigen confirm=true; la UI debe pedir confirmación antes de llamar.
  del: (path) => request(path, { method: "DELETE", params: { confirm: true } }),
};

export async function login(username, password) {
  const data = await request("/auth/login", {
    method: "POST",
    body: { username, password },
    auth: false,
  });
  setToken(data.access_token);
}
