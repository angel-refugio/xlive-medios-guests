import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createFakeBackend, callsTo } from "../../test/fakeBackend.js";
import { fakeResponse } from "../../test/helpers.js";
import { renderApp } from "../../test/renderApp.jsx";

const guest = {
  id: 1,
  full_name: "Ana López",
  organization: null,
  role: null,
  notes: null,
  approx_age: null,
  borough: null,
  categories: [],
};
const celular = { id: 1, name: "Celular", is_active: true };
const contact = {
  id: 50,
  guest_id: 1,
  contact_type: celular,
  value: "5512345678",
  note: "WhatsApp",
  source: "manual",
  verified: false,
};

const newForm = () => screen.getByRole("form", { name: "Nuevo contacto" });
const silenceErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

describe("Contactos del invitado", () => {
  it("lista los contactos con tipo, valor, nota, verificación y origen", async () => {
    createFakeBackend({
      guests: [guest],
      contacts: [
        contact,
        { ...contact, id: 51, contact_type: { id: 2, name: "Correo", is_active: true }, value: "ana@mail.com", note: null, source: "video_description", verified: true },
      ],
    });
    renderApp("/guests/1");
    expect(await screen.findByText("5512345678")).toBeInTheDocument();
    expect(screen.getByText("Celular:")).toBeInTheDocument();
    expect(screen.getByText(/WhatsApp/)).toBeInTheDocument();
    expect(screen.getByText(/Sin verificar · captura manual/)).toBeInTheDocument();
    expect(screen.getByText("ana@mail.com")).toBeInTheDocument();
    expect(screen.getByText(/Verificado · descripción del video/)).toBeInTheDocument();
  });

  it("sin contactos muestra un aviso", async () => {
    createFakeBackend({ guests: [guest] });
    renderApp("/guests/1");
    expect(await screen.findByText(/aún no tiene contactos/)).toBeInTheDocument();
  });

  it("agregar un contacto lo envía, lo muestra y limpia el formulario", async () => {
    const { fetchMock } = createFakeBackend({ guests: [guest] });
    const user = userEvent.setup();
    renderApp("/guests/1");
    await screen.findByText(/aún no tiene contactos/);
    const form = within(newForm());
    await screen.findByRole("option", { name: "Correo" });
    await user.selectOptions(form.getByLabelText("Tipo de contacto"), "Correo");
    await user.type(form.getByLabelText("Valor"), "  ana@mail.com ");
    await user.type(form.getByLabelText("Nota"), "Personal");
    await user.click(form.getByLabelText("Verificado"));
    await user.click(form.getByRole("button", { name: "Agregar contacto" }));

    expect(await screen.findByText("ana@mail.com")).toBeInTheDocument();
    expect(JSON.parse(callsTo(fetchMock, "POST", "/contacts")[0][1].body)).toEqual({
      contact_type_id: 2,
      value: "ana@mail.com",
      note: "Personal",
      verified: true,
    });
    const cleared = within(newForm());
    expect(cleared.getByLabelText("Valor")).toHaveValue("");
    expect(cleared.getByLabelText("Tipo de contacto")).toHaveValue("");
  });

  it("sin tipo o sin valor no se envía y explica qué falta", async () => {
    const { fetchMock } = createFakeBackend({ guests: [guest] });
    const user = userEvent.setup();
    renderApp("/guests/1");
    await screen.findByText(/aún no tiene contactos/);
    const form = within(newForm());
    await user.type(form.getByLabelText("Valor"), "555");
    await user.click(form.getByRole("button", { name: "Agregar contacto" }));
    expect(await form.findByRole("alert")).toHaveTextContent("Elige el tipo de contacto");

    await screen.findByRole("option", { name: "Celular" });
    await user.selectOptions(form.getByLabelText("Tipo de contacto"), "Celular");
    await user.clear(form.getByLabelText("Valor"));
    await user.type(form.getByLabelText("Valor"), "   ");
    await user.click(form.getByRole("button", { name: "Agregar contacto" }));
    expect(await form.findByRole("alert")).toHaveTextContent("El valor del contacto es obligatorio");
    expect(callsTo(fetchMock, "POST", "/contacts")).toHaveLength(0);
  });

  it("muestra el error del servidor al agregar y conserva lo escrito", async () => {
    silenceErrors();
    createFakeBackend({
      guests: [guest],
      onRequest: (url, options) =>
        options.method === "POST" && url.endsWith("/contacts")
          ? fakeResponse(422, { detail: "El tipo de contacto 1 no existe o está desactivado" })
          : undefined,
    });
    const user = userEvent.setup();
    renderApp("/guests/1");
    await screen.findByText(/aún no tiene contactos/);
    const form = within(newForm());
    await screen.findByRole("option", { name: "Celular" });
    await user.selectOptions(form.getByLabelText("Tipo de contacto"), "Celular");
    await user.type(form.getByLabelText("Valor"), "555");
    await user.click(form.getByRole("button", { name: "Agregar contacto" }));
    expect(await form.findByRole("alert")).toHaveTextContent("no existe o está desactivado");
    expect(form.getByLabelText("Valor")).toHaveValue("555");
    expect(form.getByRole("button", { name: "Agregar contacto" })).toBeEnabled();
  });

  it("sin tipos de contacto avisa que hay que crearlos en Catálogos", async () => {
    const backend = createFakeBackend({ guests: [guest] });
    backend.db.catalogs["contact-types"] = [];
    renderApp("/guests/1");
    expect(await screen.findByText(/No hay tipos de contacto/)).toBeInTheDocument();
  });

  it("editar un contacto envía los cambios con PATCH y los muestra", async () => {
    const { fetchMock } = createFakeBackend({ guests: [guest], contacts: [contact] });
    const user = userEvent.setup();
    renderApp("/guests/1");
    await user.click(await screen.findByRole("button", { name: "Editar contacto 5512345678" }));

    const form = within(screen.getByRole("form", { name: "Editar contacto" }));
    expect(form.getByLabelText("Valor")).toHaveValue("5512345678");
    expect(form.getByLabelText("Nota")).toHaveValue("WhatsApp");
    await user.clear(form.getByLabelText("Valor"));
    await user.type(form.getByLabelText("Valor"), "5599999999");
    await user.clear(form.getByLabelText("Nota"));
    await user.click(form.getByLabelText("Verificado"));
    await user.click(form.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByText("5599999999")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Editar contacto" })).not.toBeInTheDocument();
    const [url, options] = callsTo(fetchMock, "PATCH", "/contacts/50")[0];
    expect(url).toBe("/api/guests/1/contacts/50");
    expect(JSON.parse(options.body)).toEqual({
      contact_type_id: 1,
      value: "5599999999",
      note: null,
      verified: true,
    });
    expect(screen.getByText(/Verificado · captura manual/)).toBeInTheDocument();
  });

  it("cancelar la edición no envía nada", async () => {
    const { fetchMock } = createFakeBackend({ guests: [guest], contacts: [contact] });
    const user = userEvent.setup();
    renderApp("/guests/1");
    await user.click(await screen.findByRole("button", { name: "Editar contacto 5512345678" }));
    await user.click(within(screen.getByRole("form", { name: "Editar contacto" })).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("form", { name: "Editar contacto" })).not.toBeInTheDocument();
    expect(callsTo(fetchMock, "PATCH", "/contacts")).toHaveLength(0);
  });

  it("borrar pide confirmación; cancelar no borra y aceptar envía confirm=true", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const { fetchMock, db } = createFakeBackend({ guests: [guest], contacts: [contact] });
    const user = userEvent.setup();
    renderApp("/guests/1");
    const deleteButton = await screen.findByRole("button", { name: "Borrar contacto 5512345678" });

    await user.click(deleteButton);
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("5512345678"));
    expect(callsTo(fetchMock, "DELETE", "/contacts")).toHaveLength(0);
    expect(db.contacts).toHaveLength(1);

    await user.click(deleteButton);
    expect(await screen.findByText(/aún no tiene contactos/)).toBeInTheDocument();
    expect(callsTo(fetchMock, "DELETE", "/api/guests/1/contacts/50?confirm=true")).toHaveLength(1);
  });
});
