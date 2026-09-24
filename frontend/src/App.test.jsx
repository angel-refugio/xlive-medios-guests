import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App.jsx";
import { getToken, setToken } from "./api/client.js";
import { AuthProvider } from "./auth/AuthContext.jsx";
import { ROUTER_FUTURE } from "./routerFuture.js";
import { fakeResponse, mockFetch } from "./test/helpers.js";

function renderApp(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]} future={ROUTER_FUTURE}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>
  );
}

// API simulada: login válido solo con admin/clave-correcta.
function apiOk() {
  return mockFetch((url, options) => {
    if (url === "/api/auth/login") {
      const body = JSON.parse(options.body);
      return body.password === "clave-correcta"
        ? fakeResponse(200, { access_token: "tok", token_type: "bearer" })
        : fakeResponse(401, { detail: "Usuario o contraseña incorrectos" });
    }
    if (url === "/api/auth/me") return fakeResponse(200, { username: "admin", role: "administrador" });
    if (url === "/api/health") return fakeResponse(200, { status: "ok", database: "ok" });
    if (url.startsWith("/api/guests") || url.startsWith("/api/videos")) return fakeResponse(200, { items: [], total: 0, page: 1, page_size: 50 });
    return fakeResponse(404, { detail: "no encontrado" });
  });
}

describe("rutas protegidas", () => {
  it("sin sesión redirige al login", async () => {
    apiOk();
    renderApp("/guests");
    expect(await screen.findByRole("button", { name: "Entrar" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Invitados" })).not.toBeInTheDocument();
  });

  it("con token guardado válido entra directo a la pantalla pedida", async () => {
    setToken("tok");
    apiOk();
    renderApp("/guests");
    expect(await screen.findByRole("heading", { name: "Invitados" })).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();
  });

  it("con token guardado inválido vuelve al login y lo borra", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    setToken("vencido");
    mockFetch(() => fakeResponse(401, { detail: "Credenciales inválidas o sesión expirada" }));
    renderApp("/");
    expect(await screen.findByRole("button", { name: "Entrar" })).toBeInTheDocument();
    expect(getToken()).toBeNull();
  });
});

describe("login", () => {
  it("credenciales correctas: guarda sesión y muestra la app en la ruta pedida", async () => {
    apiOk();
    const user = userEvent.setup();
    renderApp("/videos");
    await user.type(await screen.findByLabelText("Usuario"), "admin");
    await user.type(screen.getByLabelText("Contraseña"), "clave-correcta");
    await user.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("heading", { name: "Videos" })).toBeInTheDocument();
    expect(getToken()).toBe("tok");
  });

  it("credenciales incorrectas: muestra el mensaje y no entra", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    apiOk();
    const user = userEvent.setup();
    renderApp("/");
    await user.type(await screen.findByLabelText("Usuario"), "admin");
    await user.type(screen.getByLabelText("Contraseña"), "mala");
    await user.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Usuario o contraseña incorrectos");
    expect(getToken()).toBeNull();
    expect(screen.getByRole("button", { name: "Entrar" })).toBeEnabled();
  });

  it("si el servidor no responde muestra el error de conexión", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const user = userEvent.setup();
    renderApp("/");
    await user.type(await screen.findByLabelText("Usuario"), "admin");
    await user.type(screen.getByLabelText("Contraseña"), "x");
    await user.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo conectar con el servidor");
  });
});

describe("layout", () => {
  it("muestra la navegación y el estado de la API en Inicio", async () => {
    setToken("tok");
    apiOk();
    renderApp("/");
    for (const name of ["Inicio", "Catálogos", "Invitados", "Videos"]) {
      expect(await screen.findByRole("link", { name })).toBeInTheDocument();
    }
    expect(await screen.findByText(/✅ OK/)).toBeInTheDocument();
  });

  it("Salir borra la sesión y vuelve al login", async () => {
    setToken("tok");
    apiOk();
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Salir" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Entrar" })).toBeInTheDocument());
    expect(getToken()).toBeNull();
  });

  it("una ruta desconocida redirige a Inicio", async () => {
    setToken("tok");
    apiOk();
    renderApp("/no-existe");
    expect(await screen.findByRole("heading", { name: "Inicio" })).toBeInTheDocument();
  });
});
