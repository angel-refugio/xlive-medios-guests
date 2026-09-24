import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createFakeBackend, callsTo } from "../test/fakeBackend.js";
import { fakeResponse } from "../test/helpers.js";
import { renderApp } from "../test/renderApp.jsx";

const guest = (id, full_name) => ({
  id,
  full_name,
  organization: null,
  role: null,
  notes: null,
  approx_age: null,
  borough: null,
  categories: [],
});
const video = (id, title) => ({
  id,
  youtube_video_id: `yt${id}`,
  title,
  description: null,
  published_at: null,
  source: "manual",
  guest_status: "pending",
  video_type: null,
  program: null,
  event_borough: null,
  part_of_video_id: null,
});

const ana = guest(1, "Ana López");
const luis = guest(2, "Luis Pérez");
const v1 = video(1, "Entrevista con Ana");
const v2 = video(2, "Evento en Coyoacán");
const link = { id: 70, guest_id: 1, video_id: 1, notes: "Habló de su gira" };

const setup = (extra = {}) =>
  createFakeBackend({ guests: [ana, luis], videos: [v1, v2], participations: [link], pageSize: 50, ...extra });
const form = () => within(screen.getByRole("form", { name: "Nueva participación" }));
const silenceErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

describe("Participaciones desde el video", () => {
  it("lista los invitados del video con sus notas y enlace al invitado", async () => {
    setup();
    renderApp("/videos/1");
    expect(await screen.findByRole("link", { name: "Ana López" })).toHaveAttribute("href", "/guests/1");
    expect(screen.getByText(/Habló de su gira/)).toBeInTheDocument();
  });

  it("un video sin invitados lo indica", async () => {
    setup();
    renderApp("/videos/2");
    expect(await screen.findByText(/aún no tiene invitados vinculados/)).toBeInTheDocument();
  });

  it("agregar un invitado: no ofrece los ya vinculados y envía la participación", async () => {
    const { fetchMock } = setup();
    const user = userEvent.setup();
    renderApp("/videos/1");
    await screen.findByRole("link", { name: "Ana López" });
    await form().findByRole("option", { name: "Luis Pérez" });
    expect(form().queryByRole("option", { name: "Ana López" })).not.toBeInTheDocument();

    await user.selectOptions(form().getByLabelText("Invitado"), "Luis Pérez");
    await user.type(form().getByLabelText("Notas"), "Presentó su disco");
    await user.click(form().getByRole("button", { name: "Agregar participación" }));

    expect(await screen.findByRole("link", { name: "Luis Pérez" })).toHaveAttribute("href", "/guests/2");
    const [url, options] = callsTo(fetchMock, "POST", "/participations")[0];
    expect(url).toBe("/api/guests/2/participations");
    expect(JSON.parse(options.body)).toEqual({ video_id: 1, notes: "Presentó su disco" });
    expect(form().getByLabelText("Invitado")).toHaveValue("");
    expect(form().getByLabelText("Notas")).toHaveValue("");
  });

  it("sin elegir invitado no se envía", async () => {
    const { fetchMock } = setup();
    const user = userEvent.setup();
    renderApp("/videos/1");
    await screen.findByRole("link", { name: "Ana López" });
    await user.click(form().getByRole("button", { name: "Agregar participación" }));
    expect(await form().findByRole("alert")).toHaveTextContent("Elige un invitado");
    expect(callsTo(fetchMock, "POST", "/participations")).toHaveLength(0);
  });

  it("muestra el error del servidor al agregar (por ejemplo, ya participa)", async () => {
    silenceErrors();
    setup({
      onRequest: (url, options) =>
        options.method === "POST" && url.endsWith("/participations")
          ? fakeResponse(409, { detail: "El invitado 2 ya participa en el video 1" })
          : undefined,
    });
    const user = userEvent.setup();
    renderApp("/videos/1");
    await form().findByRole("option", { name: "Luis Pérez" });
    await user.selectOptions(form().getByLabelText("Invitado"), "Luis Pérez");
    await user.click(form().getByRole("button", { name: "Agregar participación" }));
    expect(await form().findByRole("alert")).toHaveTextContent("ya participa en el video 1");
    expect(form().getByLabelText("Invitado")).toHaveValue("2"); // conserva la selección
  });

  it("avisa cuando solo se muestran los primeros 200 y hay más", async () => {
    setup({
      onRequest: (url) =>
        url.startsWith("/api/guests?page_size=200")
          ? fakeResponse(200, { items: [luis], total: 350, page: 1, page_size: 200 })
          : undefined,
    });
    renderApp("/videos/1");
    expect(await screen.findByText(/Se muestran 1 de 350/)).toBeInTheDocument();
  });

  it("editar las notas envía PATCH y se puede dejar vacío (null)", async () => {
    const { fetchMock } = setup();
    const user = userEvent.setup();
    renderApp("/videos/1");
    await user.click(await screen.findByRole("button", { name: "Editar notas de Ana López" }));
    const edit = within(screen.getByRole("form", { name: "Editar notas" }));
    expect(edit.getByLabelText("Notas de Ana López")).toHaveValue("Habló de su gira");
    await user.clear(edit.getByLabelText("Notas de Ana López"));
    await user.type(edit.getByLabelText("Notas de Ana López"), "Nueva nota");
    await user.click(edit.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByText(/Nueva nota/)).toBeInTheDocument();
    const [url, options] = callsTo(fetchMock, "PATCH", "/participations/70")[0];
    expect(url).toBe("/api/guests/1/participations/70");
    expect(JSON.parse(options.body)).toEqual({ notes: "Nueva nota" });

    await user.click(screen.getByRole("button", { name: "Editar notas de Ana López" }));
    await user.clear(screen.getByLabelText("Notas de Ana López"));
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await screen.findByRole("button", { name: "Editar notas de Ana López" });
    expect(JSON.parse(callsTo(fetchMock, "PATCH", "/participations/70")[1][1].body)).toEqual({ notes: null });
  });

  it("cancelar la edición de notas no envía nada", async () => {
    const { fetchMock } = setup();
    const user = userEvent.setup();
    renderApp("/videos/1");
    await user.click(await screen.findByRole("button", { name: "Editar notas de Ana López" }));
    await user.click(within(screen.getByRole("form", { name: "Editar notas" })).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("form", { name: "Editar notas" })).not.toBeInTheDocument();
    expect(callsTo(fetchMock, "PATCH", "/participations")).toHaveLength(0);
  });

  it("quitar pide confirmación; cancelar no borra y aceptar envía confirm=true sin borrar invitado ni video", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const { fetchMock, db } = setup();
    const user = userEvent.setup();
    renderApp("/videos/1");
    const remove = await screen.findByRole("button", { name: "Quitar Ana López" });

    await user.click(remove);
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("No se borra el invitado ni el video"));
    expect(callsTo(fetchMock, "DELETE", "/participations")).toHaveLength(0);

    await user.click(remove);
    expect(await screen.findByText(/aún no tiene invitados vinculados/)).toBeInTheDocument();
    expect(callsTo(fetchMock, "DELETE", "/api/guests/1/participations/70?confirm=true")).toHaveLength(1);
    expect(db.guests).toHaveLength(2);
    expect(db.videos).toHaveLength(2);
  });
});

describe("Participaciones desde el invitado", () => {
  it("lista los videos del invitado con notas y enlace al video", async () => {
    setup();
    renderApp("/guests/1");
    expect(await screen.findByRole("link", { name: "Entrevista con Ana" })).toHaveAttribute("href", "/videos/1");
    expect(screen.getByText(/Habló de su gira/)).toBeInTheDocument();
  });

  it("un invitado sin participaciones lo indica", async () => {
    setup();
    renderApp("/guests/2");
    expect(await screen.findByText(/aún no tiene participaciones/)).toBeInTheDocument();
  });

  it("agregar un video: no ofrece los ya vinculados y envía la participación", async () => {
    const { fetchMock } = setup();
    const user = userEvent.setup();
    renderApp("/guests/1");
    await screen.findByRole("link", { name: "Entrevista con Ana" });
    await form().findByRole("option", { name: "Evento en Coyoacán" });
    expect(form().queryByRole("option", { name: "Entrevista con Ana" })).not.toBeInTheDocument();

    await user.selectOptions(form().getByLabelText("Video"), "Evento en Coyoacán");
    await user.click(form().getByRole("button", { name: "Agregar participación" }));

    expect(await screen.findByRole("link", { name: "Evento en Coyoacán" })).toHaveAttribute("href", "/videos/2");
    const [url, options] = callsTo(fetchMock, "POST", "/participations")[0];
    expect(url).toBe("/api/guests/1/participations");
    expect(JSON.parse(options.body)).toEqual({ video_id: 2, notes: null });
  });

  it("sin elegir video no se envía", async () => {
    const { fetchMock } = setup();
    const user = userEvent.setup();
    renderApp("/guests/2");
    await screen.findByText(/aún no tiene participaciones/);
    await user.click(form().getByRole("button", { name: "Agregar participación" }));
    expect(await form().findByRole("alert")).toHaveTextContent("Elige un video");
    expect(callsTo(fetchMock, "POST", "/participations")).toHaveLength(0);
  });

  it("quitar desde el invitado usa la misma ruta con confirm=true", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { fetchMock, db } = setup();
    const user = userEvent.setup();
    renderApp("/guests/1");
    await user.click(await screen.findByRole("button", { name: "Quitar Entrevista con Ana" }));
    expect(await screen.findByText(/aún no tiene participaciones/)).toBeInTheDocument();
    expect(callsTo(fetchMock, "DELETE", "/api/guests/1/participations/70?confirm=true")).toHaveLength(1);
    expect(db.participations).toHaveLength(0);
  });

  it("muestra el error si falla la carga de participaciones", async () => {
    silenceErrors();
    setup({
      onRequest: (url) =>
        url === "/api/guests/1/participations" ? fakeResponse(500, { detail: "Base de datos no disponible" }) : undefined,
    });
    renderApp("/guests/1");
    expect(await screen.findByRole("alert")).toHaveTextContent("Base de datos no disponible");
  });
});
