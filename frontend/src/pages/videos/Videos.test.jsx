import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createFakeBackend, callsTo } from "../../test/fakeBackend.js";
import { fakeResponse } from "../../test/helpers.js";
import { renderApp } from "../../test/renderApp.jsx";

const v1 = {
  id: 1,
  youtube_video_id: "abc123",
  title: "Entrevista con Ana",
  description: "Charla sobre su gira",
  published_at: "2024-05-01T10:30:00Z",
  source: "manual",
  guest_status: "has_guests",
  video_type: { id: 1, name: "Entrevista", is_active: true },
  program: { id: 1, name: "Buenos días", is_active: true },
  event_borough: null,
  part_of_video_id: null,
};
const v2 = {
  id: 2,
  youtube_video_id: "yt999",
  title: "Evento en Coyoacán",
  description: null,
  published_at: null,
  source: "youtube",
  guest_status: "pending",
  video_type: null,
  program: null,
  event_borough: { id: 1, name: "Coyoacán", is_active: true },
  part_of_video_id: 1,
};
const v3 = { ...v2, id: 3, youtube_video_id: "man3", title: "Video sin datos", source: "manual", event_borough: null, part_of_video_id: null };

const silenceErrors = () => vi.spyOn(console, "error").mockImplementation(() => {});

describe("Lista de videos", () => {
  it("muestra los videos con sus datos, origen y estado de invitados", async () => {
    createFakeBackend({ videos: [v1, v2], pageSize: 50 });
    renderApp("/videos");
    expect(await screen.findByRole("link", { name: "Entrevista con Ana" })).toHaveAttribute("href", "/videos/1");
    const rows = screen.getAllByRole("row");
    for (const text of ["abc123", "2024-05-01", "Entrevista", "Buenos días", "Con invitados", "Manual"]) {
      expect(rows[1]).toHaveTextContent(text);
    }
    for (const text of ["yt999", "Pendiente de revisar", "YouTube"]) {
      expect(rows[2]).toHaveTextContent(text);
    }
    expect(rows[2].textContent.match(/—/g)).toHaveLength(3); // sin fecha, tipo ni programa
  });

  it("sin videos muestra un aviso", async () => {
    createFakeBackend();
    renderApp("/videos");
    expect(await screen.findByText(/Todavía no hay videos/)).toBeInTheDocument();
  });

  it("filtra por origen y lo refleja en la petición", async () => {
    const { fetchMock } = createFakeBackend({ videos: [v1, v2, v3], pageSize: 50 });
    const user = userEvent.setup();
    renderApp("/videos");
    await screen.findByText("Evento en Coyoacán");

    await user.selectOptions(screen.getByLabelText("Origen"), "Manuales");
    await waitFor(() => expect(screen.queryByText("Evento en Coyoacán")).not.toBeInTheDocument());
    expect(screen.getByText("Entrevista con Ana")).toBeInTheDocument();
    expect(screen.getByText("Video sin datos")).toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", "source=manual")).toHaveLength(1);

    await user.selectOptions(screen.getByLabelText("Origen"), "Todos");
    expect(await screen.findByText("Evento en Coyoacán")).toBeInTheDocument();
  });

  it("un filtro sin resultados lo dice", async () => {
    createFakeBackend({ videos: [v1], pageSize: 50 });
    const user = userEvent.setup();
    renderApp("/videos");
    await screen.findByText("Entrevista con Ana");
    await user.selectOptions(screen.getByLabelText("Origen"), "YouTube");
    expect(await screen.findByText("No hay videos con ese origen.")).toBeInTheDocument();
  });

  it("pagina y Siguiente muestra la segunda página", async () => {
    createFakeBackend({ videos: [v1, v2, v3], pageSize: 2 });
    const user = userEvent.setup();
    renderApp("/videos");
    expect(await screen.findByText("Página 1 de 2 · 3 videos")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText("Video sin datos")).toBeInTheDocument();
    expect(screen.getByText("Página 2 de 2 · 3 videos")).toBeInTheDocument();
  });

  it("muestra el error si falla la carga", async () => {
    silenceErrors();
    createFakeBackend({
      onRequest: (url) => (url.startsWith("/api/videos") ? fakeResponse(500, { detail: "Base de datos no disponible" }) : undefined),
    });
    renderApp("/videos");
    expect(await screen.findByRole("alert")).toHaveTextContent("Base de datos no disponible");
  });

  it("'Nuevo video' abre el formulario", async () => {
    createFakeBackend({ videos: [v1] });
    const user = userEvent.setup();
    renderApp("/videos");
    await user.click(await screen.findByRole("link", { name: "Nuevo video" }));
    expect(await screen.findByRole("heading", { name: "Nuevo video" })).toBeInTheDocument();
  });
});

describe("Formulario de video", () => {
  it("crear con lo mínimo: ID y título; lo demás va vacío", async () => {
    const { fetchMock } = createFakeBackend();
    const user = userEvent.setup();
    renderApp("/videos/new");
    await user.type(await screen.findByLabelText("ID de YouTube"), " nuevo1 ");
    await user.type(screen.getByLabelText("Título"), "Mi video");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("heading", { name: "Mi video" })).toBeInTheDocument();
    expect(JSON.parse(callsTo(fetchMock, "POST", "/api/videos")[0][1].body)).toEqual({
      youtube_video_id: "nuevo1",
      title: "Mi video",
      description: null,
      published_at: null,
      video_type_id: null,
      program_id: null,
      event_borough_id: null,
      part_of_video_id: null,
      guest_status: "pending",
    });
  });

  it("crear con todos los datos", async () => {
    const { fetchMock } = createFakeBackend({ videos: [v1] });
    const user = userEvent.setup();
    renderApp("/videos/new");
    await user.type(await screen.findByLabelText("ID de YouTube"), "full1");
    await user.type(screen.getByLabelText("Título"), "Video completo");
    await user.type(screen.getByLabelText("Descripción"), "Una descripción");
    await user.type(screen.getByLabelText("Fecha de publicación"), "2024-06-15");
    // Los catálogos cargan de forma asíncrona: se espera a que estén todas las opciones.
    await screen.findByRole("option", { name: "Evento" });
    await screen.findByRole("option", { name: "Buenos días" });
    await screen.findByRole("option", { name: "Tlalpan" });
    await screen.findByRole("option", { name: "Entrevista con Ana" });
    await user.selectOptions(screen.getByLabelText("Tipo de video"), "Evento");
    await user.selectOptions(screen.getByLabelText("Programa"), "Buenos días");
    await user.selectOptions(screen.getByLabelText("Alcaldía del evento"), "Tlalpan");
    await user.selectOptions(screen.getByLabelText("Parte de otro video"), "Entrevista con Ana");
    await user.selectOptions(screen.getByLabelText("Estado de invitados"), "Con invitados");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("heading", { name: "Video completo" })).toBeInTheDocument();
    expect(JSON.parse(callsTo(fetchMock, "POST", "/api/videos")[0][1].body)).toEqual({
      youtube_video_id: "full1",
      title: "Video completo",
      description: "Una descripción",
      published_at: "2024-06-15T00:00:00Z",
      video_type_id: 2,
      program_id: 1,
      event_borough_id: 2,
      part_of_video_id: 1,
      guest_status: "has_guests",
    });
  });

  it("ID o título solo con espacios no se envían y explican qué falta", async () => {
    const { fetchMock } = createFakeBackend();
    const user = userEvent.setup();
    renderApp("/videos/new");
    await user.type(await screen.findByLabelText("ID de YouTube"), "   ");
    await user.type(screen.getByLabelText("Título"), "Algo");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El ID de YouTube es obligatorio");

    await user.type(screen.getByLabelText("ID de YouTube"), "x1");
    await user.clear(screen.getByLabelText("Título"));
    await user.type(screen.getByLabelText("Título"), "   ");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El título es obligatorio");
    expect(callsTo(fetchMock, "POST", "/api/videos")).toHaveLength(0);
  });

  it("un ID de YouTube repetido muestra el error y conserva lo escrito", async () => {
    silenceErrors();
    createFakeBackend({ videos: [v1] });
    const user = userEvent.setup();
    renderApp("/videos/new");
    await user.type(await screen.findByLabelText("ID de YouTube"), "abc123");
    await user.type(screen.getByLabelText("Título"), "Otro título");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ya existe un video con el id de YouTube 'abc123'");
    expect(screen.getByLabelText("Título")).toHaveValue("Otro título");
    expect(screen.getByRole("button", { name: "Guardar" })).toBeEnabled();
  });

  it("editar: carga los datos y, si no se toca la fecha, no la envía (conserva la hora)", async () => {
    const { fetchMock, db } = createFakeBackend({ videos: [v1, v2] });
    const user = userEvent.setup();
    renderApp("/videos/1/edit");
    expect(await screen.findByLabelText("Título")).toHaveValue("Entrevista con Ana");
    expect(screen.getByLabelText("ID de YouTube")).toHaveValue("abc123");
    expect(screen.getByLabelText("Fecha de publicación")).toHaveValue("2024-05-01");
    await waitFor(() => expect(screen.getByLabelText("Programa")).toHaveValue("1"));

    await user.clear(screen.getByLabelText("Título"));
    await user.type(screen.getByLabelText("Título"), "Entrevista con Ana (v2)");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("heading", { name: "Entrevista con Ana (v2)" })).toBeInTheDocument();
    const body = JSON.parse(callsTo(fetchMock, "PATCH", "/api/videos/1")[0][1].body);
    expect(body).not.toHaveProperty("published_at");
    expect(body).toMatchObject({ title: "Entrevista con Ana (v2)", youtube_video_id: "abc123", program_id: 1, video_type_id: 1 });
    expect(db.videos[0].published_at).toBe("2024-05-01T10:30:00Z");
  });

  it("editar: si se cambia la fecha, se envía", async () => {
    const { fetchMock } = createFakeBackend({ videos: [v1] });
    const user = userEvent.setup();
    renderApp("/videos/1/edit");
    const date = await screen.findByLabelText("Fecha de publicación");
    await user.clear(date);
    await user.type(date, "2024-07-01");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await screen.findByRole("heading", { name: "Entrevista con Ana" });
    expect(JSON.parse(callsTo(fetchMock, "PATCH", "/api/videos/1")[0][1].body).published_at).toBe("2024-07-01T00:00:00Z");
  });

  it("editar: vaciar un opcional envía null", async () => {
    const { fetchMock } = createFakeBackend({ videos: [v1] });
    const user = userEvent.setup();
    renderApp("/videos/1/edit");
    await waitFor(() => expect(screen.getByLabelText("Programa")).toHaveValue("1"));
    await user.selectOptions(screen.getByLabelText("Programa"), "— Sin programa —");
    await user.clear(screen.getByLabelText("Descripción"));
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await screen.findByRole("heading", { name: "Entrevista con Ana" });
    expect(JSON.parse(callsTo(fetchMock, "PATCH", "/api/videos/1")[0][1].body)).toMatchObject({
      program_id: null,
      description: null,
    });
  });

  it("editar un video de YouTube: el ID no se puede cambiar ni se envía", async () => {
    const { fetchMock } = createFakeBackend({ videos: [v1, v2] });
    const user = userEvent.setup();
    renderApp("/videos/2/edit");
    expect(await screen.findByLabelText("ID de YouTube")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await screen.findByRole("heading", { name: "Evento en Coyoacán" });
    expect(JSON.parse(callsTo(fetchMock, "PATCH", "/api/videos/2")[0][1].body)).not.toHaveProperty("youtube_video_id");
  });

  it("'Parte de otro video' no ofrece el propio video", async () => {
    createFakeBackend({ videos: [v1, v2] });
    renderApp("/videos/1/edit");
    const select = await screen.findByLabelText("Parte de otro video");
    await within(select).findByRole("option", { name: "Evento en Coyoacán" });
    expect(within(select).queryByRole("option", { name: "Entrevista con Ana" })).not.toBeInTheDocument();
  });

  it("editar un video inexistente muestra el error", async () => {
    silenceErrors();
    createFakeBackend();
    renderApp("/videos/77/edit");
    expect(await screen.findByRole("alert")).toHaveTextContent("No existe el video 77");
  });
});

describe("Detalle de video", () => {
  it("muestra los datos del video", async () => {
    createFakeBackend({ videos: [v1] });
    renderApp("/videos/1");
    expect(await screen.findByRole("heading", { name: "Entrevista con Ana" })).toBeInTheDocument();
    for (const text of ["abc123", "Manual", "2024-05-01", "Entrevista", "Buenos días", "Con invitados", "Charla sobre su gira"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it("un video parte de otro enlaza al original y muestra guiones donde falta información", async () => {
    createFakeBackend({ videos: [v1, v2] });
    renderApp("/videos/2");
    await screen.findByRole("heading", { name: "Evento en Coyoacán" });
    expect(screen.getByRole("link", { name: "Ver video original" })).toHaveAttribute("href", "/videos/1");
    expect(screen.getByText("YouTube")).toBeInTheDocument();
    expect(screen.getByText("Coyoacán")).toBeInTheDocument();
    expect(screen.getAllByText("—")).toHaveLength(4); // fecha, tipo, programa, descripción
  });

  it("video inexistente muestra el error", async () => {
    silenceErrors();
    createFakeBackend();
    renderApp("/videos/77");
    expect(await screen.findByRole("alert")).toHaveTextContent("No existe el video 77");
  });

  it("borrar pide confirmación y avisa de las participaciones; cancelar no borra", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { fetchMock, db } = createFakeBackend({ videos: [v1] });
    const user = userEvent.setup();
    renderApp("/videos/1");
    await user.click(await screen.findByRole("button", { name: "Borrar video" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("participaciones"));
    expect(callsTo(fetchMock, "DELETE", "/api/videos/1")).toHaveLength(0);
    expect(db.videos).toHaveLength(1);
  });

  it("borrar confirmado envía confirm=true, borra sus participaciones y vuelve a la lista", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { fetchMock, db } = createFakeBackend({
      videos: [v1, v3],
      guests: [{ id: 1, full_name: "Ana López", categories: [], borough: null }],
      participations: [{ id: 70, guest_id: 1, video_id: 1, notes: null }],
      pageSize: 50,
    });
    const user = userEvent.setup();
    renderApp("/videos/1");
    await user.click(await screen.findByRole("button", { name: "Borrar video" }));
    expect(await screen.findByRole("heading", { name: "Videos" })).toBeInTheDocument();
    expect(callsTo(fetchMock, "DELETE", "/api/videos/1?confirm=true")).toHaveLength(1);
    expect(db.videos.map((v) => v.id)).toEqual([3]);
    expect(db.participations).toHaveLength(0);
    expect(db.guests).toHaveLength(1); // el invitado no se borra
  });
});
