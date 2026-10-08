import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { callsTo, createFakeBackend } from "../../test/fakeBackend.js";
import { fakeResponse } from "../../test/helpers.js";
import { renderApp } from "../../test/renderApp.jsx";

const video1 = {
  id: 1,
  youtube_video_id: "abc123",
  title: "con Karimm Kury",
  description: null,
  published_at: null,
  source: "youtube",
  guest_status: "pending",
  video_type: null,
  program: null,
  event_borough: null,
  part_of_video_id: null,
};

const guestCandidate1 = {
  id: 10,
  video_id: 1,
  extracted_name: "Karimm Kury",
  found_in_title: true,
  found_in_description: false,
  is_possible_group: false,
  category_match: null,
  category_is_new_suggestion: false,
  raw_confidence: 0.5,
  adjusted_confidence: 0.65,
  evidence: "con Karimm Kury",
  extraction_method: "regex",
  status: "pending",
  linked_guest_id: null,
  reviewed_at: null,
  created_at: "2024-01-01T00:00:00Z",
};

const contactCandidate1 = {
  id: 20,
  video_id: 1,
  guest_candidate_id: null,
  type_hint: "instagram",
  value: "@karimmkury",
  raw_confidence: 0.6,
  extraction_method: "regex",
  status: "pending",
  linked_contact_id: null,
  reviewed_at: null,
  created_at: "2024-01-01T00:00:00Z",
};

// Contacto que la IA propone con relación y evidencia, pero de un tipo que el catálogo no tiene.
const dubiousContact = {
  ...contactCandidate1,
  id: 22,
  type_hint: "Contacto",
  value: "karim@mail.com",
  relationship_name: "manager",
  evidence: "Contrataciones: karim@mail.com",
  doubtful: true,
  doubtful_reason: "tipo no registrado",
  guest_name: "Karimm Kury",
};

const noGuestsVideo = {
  ...video1,
  id: 2,
  youtube_video_id: "sin1",
  title: "Resumen semanal",
  guest_status: "no_guests",
};

describe("Staging Review: pestañas", () => {
  it("/staging redirige a la revisión por video", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    renderApp("/staging");
    expect(await screen.findByText("Staging Review")).toBeInTheDocument();
    expect(await screen.findByRole("article", { name: "con Karimm Kury" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Revisión por video" })).toHaveClass("active");
  });
});

describe("Revisión por video", () => {
  it("muestra el video con sus invitados candidatos editables y la confianza", async () => {
    createFakeBackend({ videos: [{ ...video1, description: "Texto de la descripción" }], guestCandidates: [guestCandidate1] });
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    expect(within(card).getByLabelText("Nombre de Karimm Kury")).toHaveValue("Karimm Kury");
    expect(within(card).getByText(/65%/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Ver en YouTube" })).toHaveAttribute(
      "href", "https://www.youtube.com/watch?v=abc123"
    );
    expect(within(card).getByText("Texto de la descripción")).toBeInTheDocument();
  });

  it("los filtros muestran contadores y cambian la lista", async () => {
    createFakeBackend({ videos: [video1, noGuestsVideo], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    await screen.findByRole("article", { name: "con Karimm Kury" });
    // Los filtros se buscan dentro de su grupo: la tarjeta también tiene un botón "Sin invitados".
    const filters = within(await screen.findByRole("group", { name: "Filtros de revisión" }));
    expect(await filters.findByRole("button", { name: /^Pendientes/ })).toHaveTextContent("1");
    expect(filters.getByRole("button", { name: /^Sin invitados/ })).toHaveTextContent("1");
    expect(filters.getByRole("button", { name: /^Con contactos/ })).toHaveTextContent("0");

    await user.click(filters.getByRole("button", { name: /^Sin invitados/ }));
    expect(await screen.findByRole("article", { name: "Resumen semanal" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "con Karimm Kury" })).not.toBeInTheDocument();
  });

  it("un filtro vacío lo dice", async () => {
    createFakeBackend({ videos: [video1] });
    renderApp("/staging/review");
    expect(await screen.findByText(/No hay videos con invitados candidatos por revisar/)).toBeInTheDocument();
  });

  it("busca por título", async () => {
    const otro = { ...video1, id: 3, youtube_video_id: "otro", title: "Deportes y política" };
    const { fetchMock } = createFakeBackend({
      videos: [video1, otro],
      guestCandidates: [guestCandidate1, { ...guestCandidate1, id: 11, video_id: 3, extracted_name: "Luis" }],
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.type(screen.getByLabelText("Buscar por título"), "deportes");
    await user.click(screen.getByRole("button", { name: "Buscar" }));

    expect(await screen.findByRole("article", { name: "Deportes y política" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "con Karimm Kury" })).not.toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", "q=deportes").length).toBeGreaterThan(0);
  });

  it('"Correcto" acepta todos los candidatos del video y lo quita de la lista', async () => {
    const { fetchMock, db } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(screen.getByText(/No hay videos con invitados candidatos/)).toBeInTheDocument());
    const body = JSON.parse(callsTo(fetchMock, "POST", "/staging/review/videos/1/resolve")[0][1].body);
    expect(body).toEqual({ guests: [{ candidate_id: 10 }], reject_candidate_ids: [], added_guests: [] });
    expect(db.guests).toHaveLength(1);
    expect(db.participations).toHaveLength(1);
    expect(db.videos[0].guest_status).toBe("has_guests");
  });

  it("envía el nombre corregido solo si se editó", async () => {
    const { fetchMock } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    const input = within(card).getByLabelText("Nombre de Karimm Kury");
    await user.clear(input);
    await user.type(input, "Karimm  Kuri");
    await user.click(within(card).getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(1));
    const body = JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body);
    expect(body.guests).toEqual([{ candidate_id: 10, full_name: "Karimm Kuri" }]);
  });

  it("no deja aceptar un invitado sin nombre", async () => {
    const { fetchMock } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.clear(within(card).getByLabelText("Nombre de Karimm Kury"));
    await user.click(within(card).getByRole("button", { name: "Correcto" }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("sin nombre");
    expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(0);
  });

  it("quita un candidato y descarta el video cuando no queda ninguno", async () => {
    const { fetchMock, db } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Quitar Karimm Kury" }));
    expect(within(card).queryByRole("button", { name: "Correcto" })).not.toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Descartar candidatos" }));

    await waitFor(() => expect(db.guestCandidates[0].status).toBe("rejected"));
    const body = JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body);
    expect(body).toEqual({ guests: [], reject_candidate_ids: [10], added_guests: [] });
    expect(db.guests).toHaveLength(0);
    expect(db.videos[0].guest_status).toBe("pending");
  });

  it("restaura un candidato que se quitó por error", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Quitar Karimm Kury" }));
    await user.click(within(card).getByRole("button", { name: "Restaurar Karimm Kury" }));
    expect(within(card).getByRole("button", { name: "Correcto" })).toBeInTheDocument();
  });

  it("agrega un invitado que la extracción no encontró", async () => {
    const { fetchMock, db } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.type(within(card).getByLabelText("Agregar invitado"), "Luis Pérez");
    await user.click(within(card).getByRole("button", { name: "Agregar" }));
    expect(within(card).getByText("agregado a mano")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(1));
    const body = JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body);
    expect(body.added_guests).toEqual([{ full_name: "Luis Pérez" }]);
    await waitFor(() => expect(db.guests.map((g) => g.full_name).sort()).toEqual(["Karimm Kury", "Luis Pérez"]));
  });

  it('"Sin invitados" marca el video y rechaza los candidatos', async () => {
    const { fetchMock, db } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Sin invitados" }));

    await waitFor(() => expect(db.videos[0].guest_status).toBe("no_guests"));
    expect(JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body)).toEqual({ no_guests: true });
    expect(db.guestCandidates[0].status).toBe("rejected");
  });

  it("un video sin invitados se reclasifica agregando un invitado", async () => {
    const { db } = createFakeBackend({ videos: [noGuestsVideo] });
    const user = userEvent.setup();
    renderApp("/staging/review?filter=no_guests");
    const card = await screen.findByRole("article", { name: "Resumen semanal" });
    expect(within(card).queryByRole("button", { name: "Sin invitados" })).not.toBeInTheDocument();
    await user.type(within(card).getByLabelText("Agregar invitado"), "Ana");
    await user.click(within(card).getByRole("button", { name: "Agregar" }));
    await user.click(within(card).getByRole("button", { name: "Correcto" }));
    await waitFor(() => expect(db.videos[0].guest_status).toBe("has_guests"));
  });

  // Par de duplicados: la versión con 📱 es la copia y no se revisa.
  const original = { ...video1, id: 1, title: "Con las Estrellas", possible_duplicate_of_video_id: 2 };
  const copia = { ...video1, id: 2, youtube_video_id: "xyz", title: "Con las Estrellas 📱", possible_duplicate_of_video_id: 1 };
  const guestOfCopy = { ...guestCandidate1, id: 11, video_id: 2 };

  it("la copia con 📱 se ignora por completo: no hay tarjeta, ni contador, ni filtro de copias", async () => {
    createFakeBackend({ videos: [original, copia], guestCandidates: [guestCandidate1, guestOfCopy] });
    renderApp("/staging/review");
    await screen.findByRole("article", { name: "Con las Estrellas" });
    expect(screen.queryByRole("article", { name: "Con las Estrellas 📱" })).not.toBeInTheDocument();
    const filters = within(screen.getByRole("group", { name: "Filtros de revisión" }));
    expect(await filters.findByRole("button", { name: /^Pendientes/ })).toHaveTextContent("1");
    expect(filters.queryByRole("button", { name: /duplicad/i })).not.toBeInTheDocument();
  });

  // Videos de menos de un minuto (posibles intros): se revisan aparte, fuera de Pendientes.
  const intro = { ...video1, id: 6, youtube_video_id: "intro1", title: "Intro corto", duration_seconds: 15 };
  const introCandidate = { ...guestCandidate1, id: 12, video_id: 6, extracted_name: "Arween" };

  it("los videos de menos de un minuto salen de Pendientes y se resuelven en el chip Cortos", async () => {
    const { db } = createFakeBackend({ videos: [video1, intro], guestCandidates: [guestCandidate1, introCandidate] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    await screen.findByRole("article", { name: "con Karimm Kury" });
    expect(screen.queryByRole("article", { name: "Intro corto" })).not.toBeInTheDocument();
    const filters = within(screen.getByRole("group", { name: "Filtros de revisión" }));
    expect(await filters.findByRole("button", { name: /^Cortos/ })).toHaveTextContent(/min\)1$/);
    expect(filters.getByRole("button", { name: /^Pendientes/ })).toHaveTextContent("1");

    await user.click(filters.getByRole("button", { name: /^Cortos/ }));
    const card = within(await screen.findByRole("article", { name: "Intro corto" }));
    await user.click(card.getByRole("button", { name: "Sin invitados" }));

    await waitFor(() => expect(db.videos.find((v) => v.id === 6).guest_status).toBe("no_guests"));
    await waitFor(() => expect(filters.getByRole("button", { name: /^Cortos/ })).toHaveTextContent(/min\)0$/));
    expect(filters.getByRole("button", { name: /^Sin invitados/ })).toHaveTextContent("1");
  });

  it("al dar «Correcto» el video pasa a Revisados y ahí muestra sus invitados registrados", async () => {
    const { db } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const filters = within(await screen.findByRole("group", { name: "Filtros de revisión" }));
    expect(await filters.findByRole("button", { name: /^Revisados/ })).toHaveTextContent("0");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    await user.click(card.getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(filters.getByRole("button", { name: /^Revisados/ })).toHaveTextContent("1"));
    expect(screen.queryByRole("article", { name: "con Karimm Kury" })).not.toBeInTheDocument();
    await user.click(filters.getByRole("button", { name: /^Revisados/ }));
    const reviewed = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    expect(reviewed.getByRole("link", { name: "Karimm Kury" })).toHaveAttribute("href", `/guests/${db.guests[0].id}`);
    expect(reviewed.queryByRole("button", { name: "Sin invitados" })).not.toBeInTheDocument();   // ya tiene invitados
    expect(reviewed.queryByText(/no encontró invitados/)).not.toBeInTheDocument();
  });

  it("solo es corto lo que dura menos de 60 s: 0 s sí; 60 s o sin duración no", async () => {
    createFakeBackend({
      videos: [
        { ...video1, id: 1, title: "Justo en el corte", duration_seconds: 60 },
        { ...video1, id: 2, youtube_video_id: "b", title: "Sin duración" },
        { ...video1, id: 3, youtube_video_id: "c", title: "Duración cero", duration_seconds: 0 },
      ],
      guestCandidates: [1, 2, 3].map((id) => ({ ...guestCandidate1, id: 30 + id, video_id: id })),
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    expect(await screen.findByRole("article", { name: "Justo en el corte" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Sin duración" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Duración cero" })).not.toBeInTheDocument();

    await user.click(within(screen.getByRole("group", { name: "Filtros de revisión" })).getByRole("button", { name: /^Cortos/ }));
    expect(await screen.findByRole("article", { name: "Duración cero" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Justo en el corte" })).not.toBeInTheDocument();
  });

  // Contactos dentro de la tarjeta: se aceptan o descartan ahí mismo, junto a los invitados.
  const okContact = {
    ...contactCandidate1, id: 23, type_hint: "email", value: "ana@mail.com", relationship_name: "propio",
    guest_name: "Karimm Kury", evidence: "Contacto: ana@mail.com",
  };
  const contactBody = (fetchMock) => JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body);

  it("la tarjeta muestra cada contacto con tipo, invitado y relación ya elegidos", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], contactCandidates: [okContact] });
    renderApp("/staging/review");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    expect(card.getByRole("checkbox", { name: "Aceptar contacto ana@mail.com" })).toBeChecked();
    expect(card.getByLabelText("Tipo de ana@mail.com")).toHaveValue("2");          // email ~ Correo
    expect(card.getByLabelText("Invitado de ana@mail.com")).toHaveValue("cand:10"); // el que asignó la IA
    await waitFor(() => expect(card.getByLabelText("Relación de ana@mail.com")).toHaveValue("1")); // propio
    expect(card.getByText("Contacto: ana@mail.com")).toBeInTheDocument();
  });

  it("un contacto dudoso empieza desmarcado y avisa que se descartará", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], contactCandidates: [dubiousContact] });
    renderApp("/staging/review");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    expect(card.getByRole("checkbox", { name: "Aceptar contacto karim@mail.com" })).not.toBeChecked();
    expect(card.getByText(/Dudoso: tipo no registrado/)).toBeInTheDocument();
    expect(card.getByText("Se descartará al guardar")).toBeInTheDocument();
    expect(card.getByText("Contrataciones: karim@mail.com")).toBeInTheDocument();
  });

  it("«Correcto» acepta invitados y contactos en un solo paso", async () => {
    const { fetchMock, db } = createFakeBackend({
      videos: [video1], guestCandidates: [guestCandidate1], contactCandidates: [okContact],
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    await waitFor(() => expect(card.getByLabelText("Relación de ana@mail.com")).toHaveValue("1"));
    await user.click(card.getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(db.contacts).toHaveLength(1));
    expect(contactBody(fetchMock)).toMatchObject({
      guests: [{ candidate_id: 10 }],
      contacts: [{ candidate_id: 23, contact_type_id: 2, relationship_id: 1, guest_candidate_id: 10 }],
      reject_contact_ids: [],
    });
    expect(db.contacts[0].guest_id).toBe(db.guests.find((g) => g.full_name === "Karimm Kury").id);
  });

  it("los contactos sin marcar se descartan al guardar", async () => {
    const { fetchMock, db } = createFakeBackend({
      videos: [video1], guestCandidates: [guestCandidate1], contactCandidates: [dubiousContact],
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    await user.click(card.getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(db.contactCandidates[0].status).toBe("rejected"));
    expect(contactBody(fetchMock)).toMatchObject({ contacts: [], reject_contact_ids: [22] });
  });

  it("un dudoso se acepta marcándolo a propósito y eligiendo su tipo", async () => {
    const { fetchMock, db } = createFakeBackend({
      videos: [video1], guestCandidates: [guestCandidate1], contactCandidates: [dubiousContact],
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    await user.click(card.getByRole("checkbox", { name: "Aceptar contacto karim@mail.com" }));
    await user.click(card.getByRole("button", { name: "Correcto" }));
    expect(await card.findByRole("alert")).toHaveTextContent("Elige el tipo y el invitado");
    expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(0);   // no se envió nada

    await user.selectOptions(card.getByLabelText("Tipo de karim@mail.com"), "Correo");
    await user.click(card.getByRole("button", { name: "Correcto" }));
    await waitFor(() => expect(db.contacts).toHaveLength(1));
    expect(contactBody(fetchMock).contacts[0]).toMatchObject({ contact_type_id: 2, relationship_id: 2, guest_candidate_id: 10 });
  });

  it("si se quita al invitado, su contacto queda sin asignar y no se puede aceptar así", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], contactCandidates: [okContact] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    await user.click(card.getByRole("button", { name: "Quitar Karimm Kury" }));
    expect(card.getByLabelText("Invitado de ana@mail.com")).toHaveValue("");
    await user.click(card.getByRole("button", { name: "Descartar candidatos" }));
    expect(await card.findByRole("alert")).toHaveTextContent("Elige el tipo y el invitado");
  });

  it("un invitado agregado a mano aparece para asignarle contactos", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], contactCandidates: [okContact] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    await user.type(card.getByLabelText("Agregar invitado"), "Luis Pérez");
    await user.click(card.getByRole("button", { name: "Agregar" }));
    expect(within(card.getByLabelText("Invitado de ana@mail.com")).getByRole("option", { name: "Luis Pérez" })).toBeInTheDocument();
  });

  it("«+ Crear tipo» agrega el tipo al catálogo y lo deja elegido", async () => {
    const { fetchMock, db } = createFakeBackend({
      videos: [video1], guestCandidates: [guestCandidate1],
      contactCandidates: [{ ...dubiousContact, id: 24, type_hint: "whatsapp", value: "5512345678" }],
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    await user.click(card.getByRole("button", { name: "+ Crear tipo «Whatsapp»" }));

    await waitFor(() => expect(db.catalogs["contact-types"].some((t) => t.name === "Whatsapp")).toBe(true));
    expect(callsTo(fetchMock, "POST", "/contact-types")).toHaveLength(1);
    const created = db.catalogs["contact-types"].find((t) => t.name === "Whatsapp");
    await waitFor(() => expect(card.getByLabelText("Tipo de 5512345678")).toHaveValue(String(created.id)));
    expect(card.queryByRole("button", { name: /Crear tipo/ })).not.toBeInTheDocument();
  });

  it("no ofrece crear un tipo para pistas genéricas como handle", async () => {
    createFakeBackend({
      videos: [video1], guestCandidates: [guestCandidate1],
      contactCandidates: [{ ...dubiousContact, id: 25, type_hint: "handle", value: "@karim" }],
    });
    renderApp("/staging/review");
    const card = within(await screen.findByRole("article", { name: "con Karimm Kury" }));
    await card.findByLabelText("Tipo de @karim");
    expect(card.queryByRole("button", { name: /Crear tipo/ })).not.toBeInTheDocument();
  });

  it("el filtro Contactos dudosos cuenta y lista solo los videos con un contacto dudoso", async () => {
    createFakeBackend({
      videos: [video1, { ...noGuestsVideo, id: 3 }],
      guestCandidates: [guestCandidate1],
      contactCandidates: [dubiousContact, { ...contactCandidate1, id: 21, video_id: 3 }],
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const filters = within(await screen.findByRole("group", { name: "Filtros de revisión" }));
    expect(await filters.findByRole("button", { name: /^Contactos dudosos/ })).toHaveTextContent("1");
    expect(filters.getByRole("button", { name: /^Con contactos/ })).toHaveTextContent("2");

    await user.click(filters.getByRole("button", { name: /^Contactos dudosos/ }));
    expect(await screen.findByRole("article", { name: "con Karimm Kury" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Resumen semanal" })).not.toBeInTheDocument();
  });

  it("un error de la API se muestra en la tarjeta y no la quita", async () => {
    createFakeBackend({
      videos: [video1],
      guestCandidates: [guestCandidate1],
      onRequest: (url, options) =>
        url.includes("/resolve") && options.method === "POST"
          ? fakeResponse(409, { detail: "El candidato de invitado 10 ya fue revisado (accepted)" })
          : undefined,
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Correcto" }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("ya fue revisado");
    expect(within(card).getByRole("button", { name: "Correcto" })).toBeEnabled();
  });
});

describe("Revisión por video: programa y conductores", () => {
  const suggestion = { video_id: 1, program_name: "Buenos días", host_names: ["Dante"] };

  it("preselecciona el programa sugerido y muestra los conductores sugeridos", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], suggestions: [suggestion] });
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await waitFor(() => expect(within(card).getByLabelText("Programa")).toHaveValue("1"));
    expect(within(card).getByText("Sugerido por la ingesta")).toBeInTheDocument();
    expect(within(within(card).getByRole("list", { name: "Conductores" })).getByText(/Dante/)).toBeInTheDocument();
  });

  it('"Correcto" envía el programa y los conductores revisados', async () => {
    const { fetchMock, db } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], suggestions: [suggestion] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.type(within(card).getByLabelText("Agregar conductor"), "Mose Griffin");
    await user.click(within(card).getByRole("button", { name: "Agregar conductor" }));
    await user.click(within(card).getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(1));
    const body = JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body);
    expect(body).toMatchObject({ program_id: 1, host_names: ["Dante", "Mose Griffin"] });
    await waitFor(() => expect(db.suggestions[0].status).toBe("accepted"));
    expect(db.videos[0].program.id).toBe(1);
    expect(db.programHosts[1]).toEqual(["Dante", "Mose Griffin"]);
  });

  it("quita un conductor sugerido", async () => {
    const { fetchMock } = createFakeBackend({
      videos: [video1], guestCandidates: [guestCandidate1],
      suggestions: [{ ...suggestion, host_names: ["Dante", "Mose Griffin"] }],
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Quitar conductor Dante" }));
    await user.click(within(card).getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(1));
    expect(JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body).host_names).toEqual(["Mose Griffin"]);
  });

  it("no deja guardar conductores sin programa y lo explica", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.type(within(card).getByLabelText("Agregar conductor"), "Dante");
    await user.click(within(card).getByRole("button", { name: "Agregar conductor" }));

    expect(within(card).getByText(/Elige un programa para guardar los conductores/)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Correcto" })).toBeDisabled();
    await within(card).findByRole("option", { name: "Buenos días" });
    await user.selectOptions(within(card).getByLabelText("Programa"), "Buenos días");
    expect(within(card).getByRole("button", { name: "Correcto" })).toBeEnabled();
  });

  it("un video con solo sugerencia (sin invitados candidatos) se guarda con su propio botón", async () => {
    const { fetchMock, db } = createFakeBackend({ videos: [video1], suggestions: [suggestion] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    expect(within(card).getByText("La extracción no encontró invitados.")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Guardar programa y conductores" }));

    await waitFor(() => expect(screen.getByText(/No hay videos con invitados candidatos/)).toBeInTheDocument());
    const body = JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body);
    expect(body).toEqual({ guests: [], reject_candidate_ids: [], added_guests: [], program_id: 1, host_names: ["Dante"] });
    expect(db.videos[0].program.id).toBe(1);
  });

  it('"Sin invitados" conserva el programa y los conductores revisados', async () => {
    const { fetchMock } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], suggestions: [suggestion] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Sin invitados" }));

    await waitFor(() => expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(1));
    expect(JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body)).toEqual({
      no_guests: true, program_id: 1, host_names: ["Dante"],
    });
  });

  it("ofrece como un clic los conductores que el programa ya tiene registrados", async () => {
    const { fetchMock } = createFakeBackend({
      videos: [{ ...video1, program: { id: 1, name: "Buenos días" } }],
      guestCandidates: [guestCandidate1],
      programHosts: { 1: ["Mose Griffin"] },
    });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await waitFor(() => expect(within(card).getByLabelText("Programa")).toHaveValue("1"));
    expect(within(card).queryByText("Sugerido por la ingesta")).not.toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Agregar Mose Griffin como conductor" }));
    expect(within(within(card).getByRole("list", { name: "Conductores" })).getByText(/Mose Griffin/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Agregar Mose Griffin como conductor" })).not.toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(1));
    expect(JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body).host_names).toEqual(["Mose Griffin"]);
  });

  it("ofrece los conductores habituales de la serie aunque el texto del video no los mencione", async () => {
    createFakeBackend({
      videos: [video1], guestCandidates: [guestCandidate1],
      suggestions: [{ video_id: 1, program_name: "Buenos días", host_names: ["Dante"], usual_host_names: ["Dante", "Mose Griffin"] }],
    });
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    // Dante ya está sugerido por el texto: solo se ofrece el que falta.
    expect(await within(card).findByRole("button", { name: "Agregar Mose Griffin como conductor" })).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Agregar Dante como conductor" })).not.toBeInTheDocument();
  });
});

describe("Revisión por video: dudosos", () => {
  const withDoubtful = {
    video_id: 1, program_name: "Buenos días", host_names: [],
    doubtful_names: [
      { name: "Inframundo Crew Zihuatanejo", guess: "guest" },
      { name: "Frankgogo", guess: "unknown" },
    ],
  };

  it("muestra los nombres dudosos con la pista de la IA", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], suggestions: [withDoubtful] });
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    const list = within(within(card).getByRole("list", { name: "Dudosos" }));
    expect(list.getByText("Inframundo Crew Zihuatanejo")).toBeInTheDocument();
    expect(list.getByText("la IA cree: invitado")).toBeInTheDocument();
    expect(list.getByText("Frankgogo")).toBeInTheDocument();
    expect(list.getAllByText(/la IA cree/)).toHaveLength(1); // el de pista "unknown" no dice nada
  });

  it("→ invitado lo pasa a los invitados con un clic y se envía al aprobar", async () => {
    const { fetchMock } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], suggestions: [withDoubtful] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Inframundo Crew Zihuatanejo → invitado" }));

    expect(within(card).getByText("agregado a mano")).toBeInTheDocument();
    expect(within(within(card).getByRole("list", { name: "Dudosos" })).queryByText("Inframundo Crew Zihuatanejo")).not.toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(1));
    expect(JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body).added_guests).toEqual([
      { full_name: "Inframundo Crew Zihuatanejo" },
    ]);
  });

  it("→ conductor lo pasa a los conductores del programa", async () => {
    const { fetchMock } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], suggestions: [withDoubtful] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Frankgogo → conductor" }));
    expect(within(within(card).getByRole("list", { name: "Conductores" })).getByText(/Frankgogo/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Correcto" }));

    await waitFor(() => expect(callsTo(fetchMock, "POST", "/resolve")).toHaveLength(1));
    expect(JSON.parse(callsTo(fetchMock, "POST", "/resolve")[0][1].body)).toMatchObject({
      program_id: 1, host_names: ["Frankgogo"],
    });
  });

  it("descarta un dudoso que no es nada", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1], suggestions: [withDoubtful] });
    const user = userEvent.setup();
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    await user.click(within(card).getByRole("button", { name: "Descartar Frankgogo" }));
    expect(within(within(card).getByRole("list", { name: "Dudosos" })).queryByText("Frankgogo")).not.toBeInTheDocument();
    expect(within(card).queryByText("agregado a mano")).not.toBeInTheDocument();
  });

  it("sin dudosos no aparece la sección", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    renderApp("/staging/review");
    const card = await screen.findByRole("article", { name: "con Karimm Kury" });
    expect(within(card).queryByText("Dudosos")).not.toBeInTheDocument();
  });
});

describe("Cola de contactos candidatos", () => {
  it("muestra el candidato y acepta atribuyéndolo a un invitado elegido", async () => {
    const { fetchMock, db } = createFakeBackend({
      videos: [video1],
      contactCandidates: [contactCandidate1],
      guests: [{ id: 5, full_name: "Karimm Kury", categories: [], borough: null }],
    });
    const user = userEvent.setup();
    renderApp("/staging/contact-candidates");
    expect(await screen.findByText("@karimmkury")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Revisar" }));
    await screen.findByRole("option", { name: "Karimm Kury" });
    await user.selectOptions(screen.getByLabelText("Invitado"), "Karimm Kury");
    await user.selectOptions(screen.getByLabelText("Tipo de contacto"), "Celular");
    await user.click(screen.getByRole("button", { name: "Aceptar contacto" }));

    await waitFor(() => expect(screen.getByText(/No hay candidatos en estado/)).toBeInTheDocument());
    const body = JSON.parse(callsTo(fetchMock, "POST", "/staging/contact-candidates/20/accept")[0][1].body);
    expect(body).toMatchObject({ guest_id: 5, value: "@karimmkury" });
    expect(db.contacts).toHaveLength(1);
    expect(db.contacts[0].source).toBe("video_description");
  });

  it("muestra relación, motivo y evidencia, y propone la relación de la IA al aceptar", async () => {
    const { fetchMock } = createFakeBackend({
      videos: [video1],
      contactCandidates: [dubiousContact],
      guests: [{ id: 5, full_name: "Karimm Kury", categories: [], borough: null }],
    });
    const user = userEvent.setup();
    renderApp("/staging/contact-candidates");
    expect(await screen.findByText(/Dudoso: tipo no registrado/)).toBeInTheDocument();
    expect(screen.getByText("Contrataciones: karim@mail.com")).toBeInTheDocument();
    expect(screen.getByText(/La IA lo asignó a: Karimm Kury/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Revisar" }));
    await screen.findByRole("option", { name: "Karimm Kury" });
    // La relación llega preseleccionada con lo que propuso la IA; el invitado no.
    expect(screen.getByLabelText("Relación con el invitado")).toHaveValue("2");
    expect(screen.getByLabelText("Invitado")).toHaveValue("");
    await user.selectOptions(screen.getByLabelText("Invitado"), "Karimm Kury");
    await user.selectOptions(screen.getByLabelText("Tipo de contacto"), "Correo");
    await user.click(screen.getByRole("button", { name: "Aceptar contacto" }));

    await waitFor(() => expect(screen.getByText(/No hay candidatos en estado/)).toBeInTheDocument());
    const body = JSON.parse(callsTo(fetchMock, "POST", "/staging/contact-candidates/22/accept")[0][1].body);
    expect(body).toMatchObject({ guest_id: 5, relationship_id: 2 });
  });

  it("el filtro Solo contactos dudosos oculta los que no lo son", async () => {
    createFakeBackend({ videos: [video1], contactCandidates: [contactCandidate1, dubiousContact] });
    const user = userEvent.setup();
    renderApp("/staging/contact-candidates");
    expect(await screen.findByText("@karimmkury")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Solo contactos dudosos"));
    await waitFor(() => expect(screen.queryByText("@karimmkury")).not.toBeInTheDocument());
    expect(screen.getByText("karim@mail.com")).toBeInTheDocument();
  });

  it("exige elegir invitado y tipo antes de aceptar", async () => {
    createFakeBackend({ videos: [video1], contactCandidates: [contactCandidate1], guests: [] });
    const user = userEvent.setup();
    renderApp("/staging/contact-candidates");
    await user.click(await screen.findByRole("button", { name: "Revisar" }));
    await user.click(screen.getByRole("button", { name: "Aceptar contacto" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Elige a qué invitado pertenece");
  });
});

describe("Botón de ingesta", () => {
  it("corre un lote de 5 y muestra el resultado", async () => {
    const { fetchMock } = createFakeBackend();
    const user = userEvent.setup();
    renderApp("/staging");
    await user.click(await screen.findByRole("button", { name: "Correr ingesta ahora (5 videos)" }));

    expect(await screen.findByText(/5 procesados, 5 exitosos, 0 con error/)).toBeInTheDocument();
    const body = JSON.parse(callsTo(fetchMock, "POST", "/api/ingestion/runs")[0][1].body);
    expect(body).toEqual({ batch_size: 5 });
  });

  it("al terminar, la revisión se actualiza sola, sin recargar la página", async () => {
    let backend;
    backend = createFakeBackend({
      // Simula que la corrida dejó un video con candidatos nuevos en la base de datos.
      ingestionRun: () => {
        backend.db.videos.push(structuredClone(video1));
        backend.db.guestCandidates.push(structuredClone(guestCandidate1));
        return {
          id: 1, started_at: "2024-01-01T00:00:00Z", finished_at: "2024-01-01T00:05:00Z",
          status: "completed", trigger: "manual", requested_batch_size: 5,
          processed_count: 1, success_count: 1, error_count: 0, errors: [],
        };
      },
    });
    const user = userEvent.setup();
    renderApp("/staging");
    expect(await screen.findByText(/No hay videos con invitados candidatos/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Correr ingesta ahora (5 videos)" }));
    expect(await screen.findByRole("article", { name: "con Karimm Kury" })).toBeInTheDocument();
    expect(screen.getByText(/1 procesados, 1 exitosos, 0 con error/)).toBeInTheDocument();
  });

  it("lista los errores de la corrida", async () => {
    createFakeBackend({
      ingestionRun: {
        id: 1, started_at: "2024-01-01T00:00:00Z", finished_at: "2024-01-01T00:05:00Z",
        status: "completed", trigger: "manual", requested_batch_size: 5,
        processed_count: 5, success_count: 3, error_count: 2,
        errors: [
          { id: 10, youtube_video_id: "v1", error_message: "Error de red", created_at: "2024-01-01T00:01:00Z" },
          { id: 11, youtube_video_id: "v2", error_message: "JSON inválido", created_at: "2024-01-01T00:02:00Z" },
        ],
      },
    });
    const user = userEvent.setup();
    renderApp("/staging");
    await user.click(await screen.findByRole("button", { name: "Correr ingesta ahora (5 videos)" }));

    expect(await screen.findByText(/3 exitosos, 2 con error/)).toBeInTheDocument();
    expect(screen.getByText("v1:")).toBeInTheDocument();
    expect(screen.getByText("Error de red")).toBeInTheDocument();
    expect(screen.getByText("v2:")).toBeInTheDocument();
  });

  it("un error de la API se muestra como alerta", async () => {
    createFakeBackend({
      onRequest: (url) => (url.includes("/ingestion/runs") ? fakeResponse(422, { detail: "Falta configurar YOUTUBE_API_KEY" }) : undefined),
    });
    const user = userEvent.setup();
    renderApp("/staging");
    await user.click(await screen.findByRole("button", { name: "Correr ingesta ahora (5 videos)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Falta configurar YOUTUBE_API_KEY");
  });
});
