import { vi } from "vitest";

// Respuesta mínima compatible con lo que usa el cliente (ok, status, json).
export function fakeResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (body === undefined) throw new Error("sin cuerpo");
      return body;
    },
  };
}

// Sustituye fetch: `handler(url, options)` devuelve fakeResponse(...). Guarda las llamadas.
export function mockFetch(handler) {
  const fn = vi.fn(async (url, options = {}) => handler(url, options));
  vi.stubGlobal("fetch", fn);
  return fn;
}
