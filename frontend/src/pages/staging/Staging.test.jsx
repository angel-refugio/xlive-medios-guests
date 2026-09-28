import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { callsTo, createFakeBackend } from "../../test/fakeBackend.js";
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

const noGuestsVideo = {
  ...video1,
  id: 2,
  youtube_video_id: "sin1",
  title: "Resumen semanal",
  guest_status: "no_guests",
};

describe("Staging Review: pestañas", () => {
  it("/staging redirige a la cola de invitados candidatos", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    renderApp("/staging");
    expect(await screen.findByText("Staging Review")).toBeInTheDocument();
    expect(await screen.findByText("Karimm Kury")).toBeInTheDocument();
  });
});

describe("Cola de invitados candidatos", () => {
  it("muestra el candidato con su evidencia y confianza", async () => {
    createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    renderApp("/staging/guest-candidates");
    expect(await screen.findByText("Karimm Kury")).toBeInTheDocument();
    expect(screen.getByText(/65%/)).toBeInTheDocument();
    expect(screen.getByText(/Evidencia:.*con Karimm Kury/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "con Karimm Kury" })).toHaveAttribute("href", "/videos/1");
  });

  it("sin candidatos pendientes lo dice", async () => {
    createFakeBackend({ videos: [video1] });
    renderApp("/staging/guest-candidates");
    expect(await screen.findByText(/No hay candidatos en estado/)).toBeInTheDocument();
  });

  it("crea un invitado nuevo y lo quita de la cola", async () => {
    const { fetchMock, db } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/guest-candidates");
    await user.click(await screen.findByRole("button", { name: "Revisar" }));
    const form = await screen.findByRole("form", { name: "Crear invitado nuevo para Karimm Kury" });
    expect(within(form).getByLabelText("Nombre completo")).toHaveValue("Karimm Kury");
    await user.click(within(form).getByRole("button", { name: "Crear y aceptar" }));

    await waitFor(() => expect(screen.getByText(/No hay candidatos en estado/)).toBeInTheDocument());
    const body = JSON.parse(callsTo(fetchMock, "POST", "/staging/guest-candidates/10/accept")[0][1].body);
    expect(body.full_name).toBe("Karimm Kury");
    expect(db.guests).toHaveLength(1);
    expect(db.participations).toHaveLength(1);
    expect(db.guestCandidates[0].status).toBe("accepted");
  });

  it("sugiere invitados existentes con nombre parecido y vincula sin crear uno nuevo", async () => {
    const { fetchMock, db } = createFakeBackend({
      videos: [video1],
      guestCandidates: [guestCandidate1],
      guests: [{ id: 5, full_name: "Karimm Kury", categories: [], borough: null }],
    });
    const user = userEvent.setup();
    renderApp("/staging/guest-candidates");
    await user.click(await screen.findByRole("button", { name: "Revisar" }));
    await user.click(await screen.findByRole("button", { name: "Vincular con este" }));

    await waitFor(() => expect(screen.getByText(/No hay candidatos en estado/)).toBeInTheDocument());
    const body = JSON.parse(callsTo(fetchMock, "POST", "/staging/guest-candidates/10/accept")[0][1].body);
    expect(body).toEqual({ existing_guest_id: 5 });
    expect(db.guests).toHaveLength(1); // no se creó uno nuevo
    expect(db.participations).toHaveLength(1);
  });

  it("rechaza un candidato", async () => {
    const { db } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1] });
    const user = userEvent.setup();
    renderApp("/staging/guest-candidates");
    await user.click(await screen.findByRole("button", { name: "Revisar" }));
    await user.click(await screen.findByRole("button", { name: "Rechazar candidato" }));
    await waitFor(() => expect(db.guestCandidates[0].status).toBe("rejected"));
    expect(await screen.findByText(/No hay candidatos en estado/)).toBeInTheDocument();
  });

  it("filtra por estado", async () => {
    const rejected = { ...guestCandidate1, id: 11, status: "rejected" };
    const { fetchMock } = createFakeBackend({ videos: [video1], guestCandidates: [guestCandidate1, rejected] });
    const user = userEvent.setup();
    renderApp("/staging/guest-candidates");
    await screen.findByText("Karimm Kury");
    await user.selectOptions(screen.getByLabelText("Estado"), "Rechazado");
    await waitFor(() => expect(callsTo(fetchMock, "GET", "status=rejected")).toHaveLength(1));
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

  it("exige elegir invitado y tipo antes de aceptar", async () => {
    createFakeBackend({ videos: [video1], contactCandidates: [contactCandidate1], guests: [] });
    const user = userEvent.setup();
    renderApp("/staging/contact-candidates");
    await user.click(await screen.findByRole("button", { name: "Revisar" }));
    await user.click(screen.getByRole("button", { name: "Aceptar contacto" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Elige a qué invitado pertenece");
  });
});

describe("Videos sin invitados", () => {
  it("lista los videos marcados y permite reclasificar", async () => {
    const { fetchMock, db } = createFakeBackend({ videos: [video1, noGuestsVideo] });
    const user = userEvent.setup();
    renderApp("/staging/no-guests");
    expect(await screen.findByText("Resumen semanal")).toBeInTheDocument();
    expect(screen.queryByText("con Karimm Kury")).not.toBeInTheDocument(); // ese está 'pending'

    await user.click(screen.getByRole("button", { name: "Sí tiene invitados" }));
    expect(await screen.findByRole("heading", { name: "Resumen semanal" })).toBeInTheDocument();
    expect(db.videos.find((v) => v.id === 2).guest_status).toBe("pending");
    expect(callsTo(fetchMock, "PATCH", "/api/videos/2")).toHaveLength(1);
  });

  it("sin videos marcados lo dice", async () => {
    createFakeBackend({ videos: [video1] });
    renderApp("/staging/no-guests");
    expect(await screen.findByText(/No hay videos marcados/)).toBeInTheDocument();
  });
});
