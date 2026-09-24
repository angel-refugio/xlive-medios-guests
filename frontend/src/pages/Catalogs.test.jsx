import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "../App.jsx";
import { setToken } from "../api/client.js";
import { AuthProvider } from "../auth/AuthContext.jsx";
import { ROUTER_FUTURE } from "../routerFuture.js";
import { fakeResponse, mockFetch } from "../test/helpers.js";

// API simulada con estado: cada catálogo es una lista en memoria.
function fakeApi(initial = {}) {
  const data = {
    "guest-categories": [
      { id: 1, name: "Actor", is_active: true },
      { id: 2, name: "Cantante", is_active: true },
      { id: 3, name: "Viejo", is_active: false },
    ],
    boroughs: [{ id: 10, name: "Coyoacán", is_active: true }],
    "video-types": [],
    "contact-types": [],
    programs: [{ id: 20, name: "Buenos días", is_active: true }],
    ...initial,
  };
  let nextId = 100;
  const handler = (url, options) => {
    if (url === "/api/auth/me") return fakeResponse(200, { username: "admin", role: "administrador" });
    const [pathname, query] = url.replace("/api", "").split("?");
    const [, key, id] = pathname.split("/");
    const list = data[key];
    if (!list) return fakeResponse(404, { detail: "no encontrado" });
    const method = options.method || "GET";

    if (method === "GET") {
      const all = new URLSearchParams(query).get("include_inactive") === "true";
      return fakeResponse(200, all ? list : list.filter((i) => i.is_active));
    }
    if (method === "POST") {
      const { name } = JSON.parse(options.body);
      if (list.some((i) => i.name.toLowerCase() === name.trim().toLowerCase())) {
        return fakeResponse(409, { detail: `Ya existe un registro parecido a '${name}'` });
      }
      const item = { id: nextId++, name: name.trim(), is_active: true };
      list.push(item);
      return fakeResponse(201, item);
    }
    if (method === "PATCH") {
      const item = list.find((i) => i.id === Number(id));
      const body = JSON.parse(options.body);
      if (body.name && list.some((i) => i.id !== item.id && i.name.toLowerCase() === body.name.toLowerCase())) {
        return fakeResponse(409, { detail: `Ya existe un registro parecido a '${body.name}'` });
      }
      Object.assign(item, body);
      return fakeResponse(200, item);
    }
    return fakeResponse(405, { detail: "método no soportado" });
  };
  return { data, fetchMock: mockFetch(handler) };
}

function renderCatalogs(path = "/catalogs/guest-categories") {
  setToken("tok");
  return render(
    <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>
  );
}

function callsWith(fetchMock, method) {
  return fetchMock.mock.calls.filter(([, options]) => (options?.method || "GET") === method);
}

describe("Catálogos", () => {
  it("/catalogs redirige al primer catálogo", async () => {
    fakeApi();
    renderCatalogs("/catalogs");
    expect(await screen.findByRole("heading", { name: "Categorías de invitado" })).toBeInTheDocument();
    expect(await screen.findByText("Actor")).toBeInTheDocument();
  });

  it("una clave desconocida redirige al primer catálogo", async () => {
    fakeApi();
    renderCatalogs("/catalogs/inexistente");
    expect(await screen.findByRole("heading", { name: "Categorías de invitado" })).toBeInTheDocument();
  });

  it("muestra los activos y oculta los desactivados hasta marcar la casilla", async () => {
    fakeApi();
    const user = userEvent.setup();
    renderCatalogs();
    expect(await screen.findByText("Actor")).toBeInTheDocument();
    expect(screen.queryByText(/Viejo/)).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Mostrar desactivados"));
    expect(screen.getByText(/Viejo/)).toBeInTheDocument();
    expect(screen.getByText(/\(desactivado\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activar Viejo" })).toBeInTheDocument();
  });

  it("cambia de catálogo desde las pestañas y carga sus datos", async () => {
    const { fetchMock } = fakeApi();
    const user = userEvent.setup();
    renderCatalogs();
    await screen.findByText("Actor");
    await user.click(screen.getByRole("link", { name: "Alcaldías" }));
    expect(await screen.findByRole("heading", { name: "Alcaldías" })).toBeInTheDocument();
    expect(await screen.findByText("Coyoacán")).toBeInTheDocument();
    expect(screen.queryByText("Actor")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url.startsWith("/api/boroughs"))).toBe(true);
  });

  it("catálogo vacío muestra un aviso", async () => {
    fakeApi();
    renderCatalogs("/catalogs/video-types");
    expect(await screen.findByText(/No hay registros activos/)).toBeInTheDocument();
  });

  it("agregar: envía el nombre, limpia el campo y refresca la lista", async () => {
    const { fetchMock } = fakeApi();
    const user = userEvent.setup();
    renderCatalogs();
    await screen.findByText("Actor");

    const add = screen.getByRole("button", { name: "Agregar" });
    expect(add).toBeDisabled(); // sin nombre no se puede enviar
    await user.type(screen.getByLabelText("Nuevo nombre"), "Conductor");
    await user.click(add);

    expect(await screen.findByText("Conductor")).toBeInTheDocument();
    expect(screen.getByLabelText("Nuevo nombre")).toHaveValue("");
    expect(JSON.parse(callsWith(fetchMock, "POST")[0][1].body)).toEqual({ name: "Conductor" });
  });

  it("agregar un duplicado muestra el 409 y conserva lo escrito", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    fakeApi();
    const user = userEvent.setup();
    renderCatalogs();
    await screen.findByText("Actor");
    await user.type(screen.getByLabelText("Nuevo nombre"), "actor");
    await user.click(screen.getByRole("button", { name: "Agregar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ya existe un registro parecido");
    expect(screen.getByLabelText("Nuevo nombre")).toHaveValue("actor");
  });

  it("renombrar: edita en la fila y guarda con PATCH", async () => {
    const { fetchMock } = fakeApi();
    const user = userEvent.setup();
    renderCatalogs();
    await screen.findByText("Cantante");
    await user.click(screen.getByRole("button", { name: "Renombrar Cantante" }));

    const input = screen.getByLabelText("Nuevo nombre para Cantante");
    await user.clear(input);
    await user.type(input, "Cantautor");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByText("Cantautor")).toBeInTheDocument();
    expect(screen.queryByText("Cantante")).not.toBeInTheDocument();
    const [url, options] = callsWith(fetchMock, "PATCH")[0];
    expect(url).toBe("/api/guest-categories/2");
    expect(JSON.parse(options.body)).toEqual({ name: "Cantautor" });
  });

  it("renombrar a un nombre repetido muestra el error y mantiene la edición", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    fakeApi();
    const user = userEvent.setup();
    renderCatalogs();
    await screen.findByText("Cantante");
    await user.click(screen.getByRole("button", { name: "Renombrar Cantante" }));
    const input = screen.getByLabelText("Nuevo nombre para Cantante");
    await user.clear(input);
    await user.type(input, "ACTOR");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ya existe un registro parecido");
    expect(screen.getByLabelText("Nuevo nombre para Cantante")).toBeInTheDocument();
  });

  it("cancelar la edición no envía nada", async () => {
    const { fetchMock } = fakeApi();
    const user = userEvent.setup();
    renderCatalogs();
    await screen.findByText("Actor");
    await user.click(screen.getByRole("button", { name: "Renombrar Actor" }));
    await user.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByLabelText("Nuevo nombre para Actor")).not.toBeInTheDocument();
    expect(callsWith(fetchMock, "PATCH")).toHaveLength(0);
  });

  it("desactivar quita el registro de la lista y se puede reactivar", async () => {
    const { fetchMock } = fakeApi();
    const user = userEvent.setup();
    renderCatalogs();
    await screen.findByText("Actor");

    await user.click(screen.getByRole("button", { name: "Desactivar Actor" }));
    await waitFor(() => expect(screen.queryByText("Actor")).not.toBeInTheDocument());
    expect(JSON.parse(callsWith(fetchMock, "PATCH")[0][1].body)).toEqual({ is_active: false });

    await user.click(screen.getByLabelText("Mostrar desactivados"));
    const row = screen.getByText(/Actor/).closest("li");
    await user.click(within(row).getByRole("button", { name: "Activar Actor" }));
    await waitFor(() =>
      expect(within(screen.getByText(/Actor/).closest("li")).getByRole("button", { name: "Desactivar Actor" })).toBeInTheDocument()
    );
  });

  it("si la carga falla muestra el error", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockFetch((url) =>
      url === "/api/auth/me"
        ? fakeResponse(200, { username: "admin", role: "administrador" })
        : fakeResponse(500, { detail: "Base de datos no disponible" })
    );
    renderCatalogs();
    expect(await screen.findByRole("alert")).toHaveTextContent("Base de datos no disponible");
  });
});
