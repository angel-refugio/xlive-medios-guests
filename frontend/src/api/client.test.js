import { describe, expect, it, vi } from "vitest";
import { fakeResponse, mockFetch } from "../test/helpers.js";
import {
  ApiError,
  api,
  getToken,
  login,
  messageFromDetail,
  request,
  setToken,
  setUnauthorizedHandler,
} from "./client.js";

describe("messageFromDetail", () => {
  it("usa el texto de detail tal cual", () => {
    expect(messageFromDetail("Ya existe", 409)).toBe("Ya existe");
  });

  it("une los errores de validación 422 con su campo", () => {
    const detail = [
      { loc: ["body", "full_name"], msg: "Field required" },
      { loc: ["body", "approx_age"], msg: "too big" },
    ];
    expect(messageFromDetail(detail, 422)).toBe("full_name: Field required; approx_age: too big");
  });

  it("cae a un mensaje genérico con el código HTTP", () => {
    expect(messageFromDetail(undefined, 500)).toBe("Error HTTP 500");
  });
});

describe("request", () => {
  it("envía el token en Authorization cuando existe", async () => {
    setToken("abc");
    const fetchMock = mockFetch(() => fakeResponse(200, { ok: true }));
    await request("/health");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer abc");
  });

  it("no envía Authorization sin token", async () => {
    const fetchMock = mockFetch(() => fakeResponse(200, {}));
    await request("/health");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it("arma la query ignorando valores vacíos", async () => {
    const fetchMock = mockFetch(() => fakeResponse(200, {}));
    await api.get("/guests", { page: 2, q: "", source: undefined, activo: false });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/guests?page=2&activo=false");
  });

  it("serializa el cuerpo JSON en POST", async () => {
    const fetchMock = mockFetch(() => fakeResponse(201, { id: 1 }));
    await api.post("/programs", { name: "Buenos días" });
    const [, options] = fetchMock.mock.calls[0];
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual({ name: "Buenos días" });
  });

  it("del agrega confirm=true", async () => {
    const fetchMock = mockFetch(() => fakeResponse(204));
    await expect(api.del("/guests/5")).resolves.toBeNull();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/guests/5?confirm=true");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
  });

  it("lanza ApiError con el detail y el status", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockFetch(() => fakeResponse(409, { detail: "Ya existe un registro parecido" }));
    await expect(api.post("/programs", { name: "x" })).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      message: "Ya existe un registro parecido",
    });
  });

  it("convierte un fallo de red en ApiError con status 0", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const error = await request("/health").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
    expect(error.message).toBe("No se pudo conectar con el servidor");
  });

  it("ante 401 con sesión: borra el token y avisa al manejador", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setToken("vencido");
    mockFetch(() => fakeResponse(401, { detail: "Credenciales inválidas o sesión expirada" }));
    await expect(api.get("/guests")).rejects.toMatchObject({ status: 401 });
    expect(getToken()).toBeNull();
    expect(handler).toHaveBeenCalledTimes(1);
    setUnauthorizedHandler(null);
  });
});

describe("login", () => {
  it("guarda el token si las credenciales son correctas", async () => {
    const fetchMock = mockFetch(() => fakeResponse(200, { access_token: "tok", token_type: "bearer" }));
    await login("admin", "clave");
    expect(getToken()).toBe("tok");
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/login");
    expect(JSON.parse(options.body)).toEqual({ username: "admin", password: "clave" });
  });

  it("con credenciales incorrectas no guarda token ni dispara el manejador de 401", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(() => fakeResponse(401, { detail: "Usuario o contraseña incorrectos" }));
    await expect(login("admin", "mal")).rejects.toMatchObject({
      message: "Usuario o contraseña incorrectos",
    });
    expect(getToken()).toBeNull();
    expect(handler).not.toHaveBeenCalled();
    setUnauthorizedHandler(null);
  });
});
