import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createFakeBackend, callsTo } from "../../test/fakeBackend.js";
import { fakeResponse } from "../../test/helpers.js";
import { renderApp } from "../../test/renderApp.jsx";

const ana = {
  id: 1,
  full_name: "Ana López",
  organization: "Banda X",
  role: "Vocalista",
  notes: "Le gusta el rock",
  approx_age: 34,
  borough: { id: 1, name: "Coyoacán", is_active: true },
  categories: [{ id: 2, name: "Cantante", is_active: true }],
};
const luis = { ...ana, id: 2, full_name: "Luis Pérez", organization: null, role: null, notes: null, approx_age: null, borough: null, categories: [] };
const marta = { ...luis, id: 3, full_name: "Marta Ruiz" };

const silenceErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

describe("Lista de invitados", () => {
  it("muestra los invitados con sus datos y guiones donde falta información", async () => {
    createFakeBackend({ guests: [ana, luis], pageSize: 50 });
    renderApp("/guests");
    expect(await screen.findByRole("link", { name: "Ana López" })).toHaveAttribute("href", "/guests/1");
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Cantante");
    expect(rows[1]).toHaveTextContent("Coyoacán");
    expect(rows[1]).toHaveTextContent("34");
    expect(rows[1]).toHaveTextContent("Vocalista");
    expect(rows[2]).toHaveTextContent("Luis Pérez");
    expect(rows[2].textContent.match(/—/g)).toHaveLength(4);
  });

  it("sin invitados muestra un aviso", async () => {
    createFakeBackend({ guests: [] });
    renderApp("/guests");
    expect(await screen.findByText(/Todavía no hay invitados/)).toBeInTheDocument();
  });

  it("pagina: Siguiente pide la página 2 y Anterior regresa", async () => {
    const { fetchMock } = createFakeBackend({ guests: [ana, luis, marta], pageSize: 2 });
    const user = userEvent.setup();
    renderApp("/guests");
    expect(await screen.findByText("Página 1 de 2 · 3 invitados")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
    expect(screen.queryByText("Marta Ruiz")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText("Marta Ruiz")).toBeInTheDocument();
    expect(screen.getByText("Página 2 de 2 · 3 invitados")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
    expect(callsTo(fetchMock, "GET", "/api/guests?page=2")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Anterior" }));
    expect(await screen.findByText("Ana López")).toBeInTheDocument();
  });

  it("una página fuera de rango ofrece volver a la primera", async () => {
    createFakeBackend({ guests: [ana], pageSize: 2 });
    renderApp("/guests?page=9");
    expect(await screen.findByText(/Esta página no tiene invitados/)).toBeInTheDocument();
  });

  it("muestra el error si falla la carga", async () => {
    silenceErrors();
    createFakeBackend({
      onRequest: (url) => (url.startsWith("/api/guests") ? fakeResponse(500, { detail: "Base de datos no disponible" }) : undefined),
    });
    renderApp("/guests");
    expect(await screen.findByRole("alert")).toHaveTextContent("Base de datos no disponible");
  });

  it("'Nuevo invitado' abre el formulario", async () => {
    createFakeBackend({ guests: [ana] });
    const user = userEvent.setup();
    renderApp("/guests");
    await user.click(await screen.findByRole("link", { name: "Nuevo invitado" }));
    expect(await screen.findByRole("heading", { name: "Nuevo invitado" })).toBeInTheDocument();
  });
});

describe("Formulario de invitado", () => {
  it("crear solo con el nombre: los demás campos van vacíos (null)", async () => {
    const { fetchMock, db } = createFakeBackend();
    const user = userEvent.setup();
    renderApp("/guests/new");
    await user.type(await screen.findByLabelText("Nombre completo"), "  Carlos Vega ");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("heading", { name: "Carlos Vega" })).toBeInTheDocument();
    expect(JSON.parse(callsTo(fetchMock, "POST", "/api/guests")[0][1].body)).toEqual({
      full_name: "Carlos Vega",
      organization: null,
      role: null,
      notes: null,
      approx_age: null,
      borough_id: null,
      category_ids: [],
      new_categories: [],
    });
    expect(db.guests).toHaveLength(1);
  });

  it("un nombre solo con espacios no se envía", async () => {
    const { fetchMock } = createFakeBackend();
    const user = userEvent.setup();
    renderApp("/guests/new");
    await user.type(await screen.findByLabelText("Nombre completo"), "   ");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El nombre es obligatorio");
    expect(callsTo(fetchMock, "POST", "/api/guests")).toHaveLength(0);
  });

  it("crear con todos los datos, categoría existente y categoría nueva al vuelo", async () => {
    const { fetchMock } = createFakeBackend();
    const user = userEvent.setup();
    renderApp("/guests/new");
    await user.type(await screen.findByLabelText("Nombre completo"), "Sofía Ríos");
    await user.type(screen.getByLabelText("Organización"), "Radio Uno");
    await user.type(screen.getByLabelText("Puesto o rol"), "Conductora");
    await user.type(screen.getByLabelText("Edad aproximada"), "41");
    await user.type(screen.getByLabelText("Notas"), "Invitada frecuente");
    await screen.findByRole("option", { name: "Tlalpan" });
    await user.selectOptions(screen.getByLabelText("Alcaldía"), "Tlalpan");
    await user.click(await screen.findByLabelText("Actor"));

    await user.type(screen.getByLabelText("Nueva categoría"), "Conductor");
    await user.click(screen.getByRole("button", { name: "Agregar categoría" }));
    expect(screen.getByRole("button", { name: "Quitar Conductor" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("heading", { name: "Sofía Ríos" })).toBeInTheDocument();
    expect(JSON.parse(callsTo(fetchMock, "POST", "/api/guests")[0][1].body)).toEqual({
      full_name: "Sofía Ríos",
      organization: "Radio Uno",
      role: "Conductora",
      notes: "Invitada frecuente",
      approx_age: 41,
      borough_id: 2,
      category_ids: [1],
      new_categories: ["Conductor"],
    });
    expect(screen.getByText("Actor, Conductor")).toBeInTheDocument();
  });

  it("se puede quitar una categoría nueva antes de guardar y no repite nombres", async () => {
    createFakeBackend();
    const user = userEvent.setup();
    renderApp("/guests/new");
    const input = await screen.findByLabelText("Nueva categoría");
    await user.type(input, "Conductor{Enter}");
    await user.type(input, "conductor{Enter}");
    expect(screen.getAllByRole("button", { name: /^Quitar/ })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Quitar Conductor" }));
    expect(screen.queryByRole("button", { name: /^Quitar/ })).not.toBeInTheDocument();
  });

  it("muestra el error del servidor y se queda en el formulario", async () => {
    silenceErrors();
    createFakeBackend({
      onRequest: (url, options) =>
        options.method === "POST" && url === "/api/guests"
          ? fakeResponse(422, { detail: "La alcaldía 2 no existe o está desactivada" })
          : undefined,
    });
    const user = userEvent.setup();
    renderApp("/guests/new");
    await user.type(await screen.findByLabelText("Nombre completo"), "Ana");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("La alcaldía 2 no existe");
    expect(screen.getByRole("heading", { name: "Nuevo invitado" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar" })).toBeEnabled();
  });

  it("editar: carga los datos y al vaciar un campo se envía null", async () => {
    const { fetchMock } = createFakeBackend({ guests: [ana] });
    const user = userEvent.setup();
    renderApp("/guests/1/edit");
    expect(await screen.findByLabelText("Nombre completo")).toHaveValue("Ana López");
    expect(screen.getByLabelText("Organización")).toHaveValue("Banda X");
    expect(screen.getByLabelText("Edad aproximada")).toHaveValue(34);
    await waitFor(() => expect(screen.getByLabelText("Alcaldía")).toHaveValue("1"));
    expect(await screen.findByLabelText("Cantante")).toBeChecked();
    expect(screen.getByLabelText("Actor")).not.toBeChecked();

    await user.clear(screen.getByLabelText("Puesto o rol"));
    await user.clear(screen.getByLabelText("Edad aproximada"));
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("heading", { name: "Ana López" })).toBeInTheDocument();
    const [url, options] = callsTo(fetchMock, "PATCH", "/api/guests/1")[0];
    expect(url).toBe("/api/guests/1");
    expect(JSON.parse(options.body)).toMatchObject({
      role: null,
      approx_age: null,
      organization: "Banda X",
      borough_id: 1,
      category_ids: [2],
    });
  });

  it("editar: una categoría ya asignada pero desactivada se conserva y se marca", async () => {
    const vieja = { id: 9, name: "Vieja", is_active: false };
    const { fetchMock, db } = createFakeBackend({ guests: [{ ...ana, categories: [vieja] }] });
    db.catalogs["guest-categories"].push(vieja);
    const user = userEvent.setup();
    renderApp("/guests/1/edit");
    expect(await screen.findByLabelText(/Vieja/)).toBeChecked();
    expect(screen.getByText(/\(desactivada\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await screen.findByRole("heading", { name: "Ana López" });
    expect(JSON.parse(callsTo(fetchMock, "PATCH", "/api/guests/1")[0][1].body).category_ids).toEqual([9]);
  });

  it("editar un invitado inexistente muestra el error", async () => {
    silenceErrors();
    createFakeBackend();
    renderApp("/guests/77/edit");
    expect(await screen.findByRole("alert")).toHaveTextContent("No existe el invitado 77");
  });
});

describe("Detalle de invitado", () => {
  it("muestra los datos del invitado", async () => {
    createFakeBackend({ guests: [ana, luis] });
    renderApp("/guests/1");
    expect(await screen.findByRole("heading", { name: "Ana López" })).toBeInTheDocument();
    for (const text of ["Banda X", "Vocalista", "34", "Coyoacán", "Cantante", "Le gusta el rock"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it("invitado sin datos opcionales muestra guiones", async () => {
    createFakeBackend({ guests: [luis] });
    renderApp("/guests/2");
    await screen.findByRole("heading", { name: "Luis Pérez" });
    expect(screen.getAllByText("—")).toHaveLength(6);
  });

  it("invitado inexistente muestra el error", async () => {
    silenceErrors();
    createFakeBackend();
    renderApp("/guests/77");
    expect(await screen.findByRole("alert")).toHaveTextContent("No existe el invitado 77");
  });

  it("borrar pide confirmación; si se cancela no se envía nada", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { fetchMock, db } = createFakeBackend({ guests: [ana] });
    const user = userEvent.setup();
    renderApp("/guests/1");
    await user.click(await screen.findByRole("button", { name: "Borrar invitado" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("contactos y participaciones"));
    expect(callsTo(fetchMock, "DELETE", "/api/guests/1")).toHaveLength(0);
    expect(db.guests).toHaveLength(1);
  });

  it("borrar confirmado envía confirm=true y vuelve a la lista", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { fetchMock, db } = createFakeBackend({ guests: [ana, luis] });
    const user = userEvent.setup();
    renderApp("/guests/1");
    await user.click(await screen.findByRole("button", { name: "Borrar invitado" }));
    expect(await screen.findByRole("heading", { name: "Invitados" })).toBeInTheDocument();
    expect(callsTo(fetchMock, "DELETE", "/api/guests/1?confirm=true")).toHaveLength(1);
    expect(db.guests.map((g) => g.id)).toEqual([2]);
  });
});
