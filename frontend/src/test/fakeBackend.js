import { fakeResponse, mockFetch } from "./helpers.js";

// API simulada con estado para invitados, contactos, videos, participaciones y catálogos
// (pruebas de pantallas). `onRequest(url, options)` permite inyectar respuestas
// (p. ej. errores): si devuelve algo, se usa.
export function createFakeBackend({
  guests = [],
  contacts = [],
  videos = [],
  participations = [], // { id, guest_id, video_id, notes }
  pageSize = 2,
  onRequest,
} = {}) {
  const db = {
    guests: [...guests],
    contacts: [...contacts],
    videos: [...videos],
    participations: [...participations],
    catalogs: {
      boroughs: [
        { id: 1, name: "Coyoacán", is_active: true },
        { id: 2, name: "Tlalpan", is_active: true },
      ],
      "guest-categories": [
        { id: 1, name: "Actor", is_active: true },
        { id: 2, name: "Cantante", is_active: true },
      ],
      "contact-types": [
        { id: 1, name: "Celular", is_active: true },
        { id: 2, name: "Correo", is_active: true },
      ],
      "video-types": [
        { id: 1, name: "Entrevista", is_active: true },
        { id: 2, name: "Evento", is_active: true },
      ],
      programs: [{ id: 1, name: "Buenos días", is_active: true }],
    },
    nextId: 1000,
  };

  const catalogItem = (key, id) => (id ? db.catalogs[key].find((i) => i.id === Number(id)) ?? null : null);
  const pageOf = (list, params) => {
    const page = Number(params.get("page") || 1);
    const size = Number(params.get("page_size")) || pageSize;
    return { items: list.slice((page - 1) * size, page * size), total: list.length, page, page_size: size };
  };

  function guestFromPayload(payload, id, current) {
    const categories = (payload.category_ids ?? []).map((cid) => catalogItem("guest-categories", cid));
    for (const name of payload.new_categories ?? []) {
      let cat = db.catalogs["guest-categories"].find((c) => c.name.toLowerCase() === name.toLowerCase());
      if (!cat) {
        cat = { id: db.nextId++, name, is_active: true };
        db.catalogs["guest-categories"].push(cat);
      }
      if (!categories.includes(cat)) categories.push(cat);
    }
    return {
      id,
      full_name: payload.full_name ?? current?.full_name,
      organization: payload.organization ?? null,
      role: payload.role ?? null,
      notes: payload.notes ?? null,
      approx_age: payload.approx_age ?? null,
      borough: catalogItem("boroughs", payload.borough_id),
      categories,
    };
  }

  function videoFromPayload(payload, id, current) {
    return {
      id,
      youtube_video_id: payload.youtube_video_id ?? current?.youtube_video_id,
      title: payload.title ?? current?.title,
      description: payload.description ?? null,
      // Si el cliente no envía la fecha, se conserva la que ya tenía (como el API real).
      published_at: "published_at" in payload ? payload.published_at : current?.published_at ?? null,
      source: current?.source ?? "manual",
      guest_status: payload.guest_status ?? current?.guest_status ?? "pending",
      video_type: catalogItem("video-types", payload.video_type_id),
      program: catalogItem("programs", payload.program_id),
      event_borough: catalogItem("boroughs", payload.event_borough_id),
      part_of_video_id: payload.part_of_video_id ?? null,
    };
  }

  const participationOut = (p) => {
    const guest = db.guests.find((g) => g.id === p.guest_id);
    const video = db.videos.find((v) => v.id === p.video_id);
    return {
      id: p.id,
      guest: { id: guest.id, full_name: guest.full_name },
      video: { id: video.id, youtube_video_id: video.youtube_video_id, title: video.title, source: video.source },
      notes: p.notes ?? null,
    };
  };

  const handler = (url, options) => {
    const injected = onRequest?.(url, options);
    if (injected) return injected;

    const method = options.method || "GET";
    const [pathname, query = ""] = url.replace("/api", "").split("?");
    const params = new URLSearchParams(query);
    const body = options.body ? JSON.parse(options.body) : undefined;
    let m;

    if (pathname === "/auth/me") return fakeResponse(200, { username: "admin", role: "administrador" });

    if (
      (m = pathname.match(/^\/(boroughs|guest-categories|contact-types|video-types|programs)$/)) &&
      method === "GET"
    ) {
      return fakeResponse(200, db.catalogs[m[1]].filter((i) => i.is_active));
    }

    // ---- Invitados ----
    if (pathname === "/guests") {
      if (method === "GET") return fakeResponse(200, pageOf(db.guests, params));
      if (method === "POST") {
        const guest = guestFromPayload(body, db.nextId++);
        db.guests.push(guest);
        return fakeResponse(201, guest);
      }
    }

    if ((m = pathname.match(/^\/guests\/(\d+)$/))) {
      const index = db.guests.findIndex((g) => g.id === Number(m[1]));
      if (index === -1) return fakeResponse(404, { detail: `No existe el invitado ${m[1]}` });
      if (method === "GET") return fakeResponse(200, db.guests[index]);
      if (method === "PATCH") {
        db.guests[index] = guestFromPayload(body, db.guests[index].id, db.guests[index]);
        return fakeResponse(200, db.guests[index]);
      }
      if (method === "DELETE") {
        if (params.get("confirm") !== "true") return fakeResponse(400, { detail: "falta confirm=true" });
        db.participations = db.participations.filter((p) => p.guest_id !== db.guests[index].id);
        db.guests.splice(index, 1);
        return fakeResponse(204);
      }
    }

    // ---- Contactos ----
    if ((m = pathname.match(/^\/guests\/(\d+)\/contacts$/))) {
      const guestId = Number(m[1]);
      if (method === "GET") return fakeResponse(200, db.contacts.filter((c) => c.guest_id === guestId));
      if (method === "POST") {
        const contact = {
          id: db.nextId++,
          guest_id: guestId,
          contact_type: catalogItem("contact-types", body.contact_type_id),
          value: body.value,
          note: body.note ?? null,
          source: "manual",
          verified: body.verified ?? false,
        };
        db.contacts.push(contact);
        return fakeResponse(201, contact);
      }
    }

    if ((m = pathname.match(/^\/guests\/(\d+)\/contacts\/(\d+)$/))) {
      const index = db.contacts.findIndex((c) => c.id === Number(m[2]));
      if (index === -1) return fakeResponse(404, { detail: "No existe el contacto" });
      if (method === "PATCH") {
        const { contact_type_id, ...rest } = body;
        Object.assign(db.contacts[index], rest, {
          contact_type: catalogItem("contact-types", contact_type_id),
        });
        return fakeResponse(200, db.contacts[index]);
      }
      if (method === "DELETE") {
        if (params.get("confirm") !== "true") return fakeResponse(400, { detail: "falta confirm=true" });
        db.contacts.splice(index, 1);
        return fakeResponse(204);
      }
    }

    // ---- Videos ----
    if (pathname === "/videos") {
      if (method === "GET") {
        const source = params.get("source");
        return fakeResponse(200, pageOf(source ? db.videos.filter((v) => v.source === source) : db.videos, params));
      }
      if (method === "POST") {
        if (db.videos.some((v) => v.youtube_video_id === body.youtube_video_id)) {
          return fakeResponse(409, { detail: `Ya existe un video con el id de YouTube '${body.youtube_video_id}'` });
        }
        const video = videoFromPayload(body, db.nextId++);
        db.videos.push(video);
        return fakeResponse(201, video);
      }
    }

    if ((m = pathname.match(/^\/videos\/(\d+)$/))) {
      const index = db.videos.findIndex((v) => v.id === Number(m[1]));
      if (index === -1) return fakeResponse(404, { detail: `No existe el video ${m[1]}` });
      if (method === "GET") return fakeResponse(200, db.videos[index]);
      if (method === "PATCH") {
        db.videos[index] = videoFromPayload(body, db.videos[index].id, db.videos[index]);
        return fakeResponse(200, db.videos[index]);
      }
      if (method === "DELETE") {
        if (params.get("confirm") !== "true") return fakeResponse(400, { detail: "falta confirm=true" });
        db.participations = db.participations.filter((p) => p.video_id !== db.videos[index].id);
        db.videos.splice(index, 1);
        return fakeResponse(204);
      }
    }

    // ---- Participaciones ----
    if ((m = pathname.match(/^\/videos\/(\d+)\/participations$/)) && method === "GET") {
      return fakeResponse(200, db.participations.filter((p) => p.video_id === Number(m[1])).map(participationOut));
    }

    if ((m = pathname.match(/^\/guests\/(\d+)\/participations$/))) {
      const guestId = Number(m[1]);
      if (!db.guests.some((g) => g.id === guestId)) return fakeResponse(404, { detail: `No existe el invitado ${guestId}` });
      if (method === "GET") {
        return fakeResponse(200, db.participations.filter((p) => p.guest_id === guestId).map(participationOut));
      }
      if (method === "POST") {
        if (!db.videos.some((v) => v.id === body.video_id)) return fakeResponse(422, { detail: `El video ${body.video_id} no existe` });
        if (db.participations.some((p) => p.guest_id === guestId && p.video_id === body.video_id)) {
          return fakeResponse(409, { detail: `El invitado ${guestId} ya participa en el video ${body.video_id}` });
        }
        const participation = { id: db.nextId++, guest_id: guestId, video_id: body.video_id, notes: body.notes ?? null };
        db.participations.push(participation);
        return fakeResponse(201, participationOut(participation));
      }
    }

    if ((m = pathname.match(/^\/guests\/(\d+)\/participations\/(\d+)$/))) {
      const index = db.participations.findIndex((p) => p.id === Number(m[2]) && p.guest_id === Number(m[1]));
      if (index === -1) return fakeResponse(404, { detail: "No existe la participación" });
      if (method === "PATCH") {
        db.participations[index].notes = body.notes ?? null;
        return fakeResponse(200, participationOut(db.participations[index]));
      }
      if (method === "DELETE") {
        if (params.get("confirm") !== "true") return fakeResponse(400, { detail: "falta confirm=true" });
        db.participations.splice(index, 1);
        return fakeResponse(204);
      }
    }

    return fakeResponse(404, { detail: `Ruta no simulada: ${method} ${pathname}` });
  };

  return { db, fetchMock: mockFetch(handler) };
}

export function callsTo(fetchMock, method, urlPart) {
  return fetchMock.mock.calls.filter(
    ([url, options]) => (options?.method || "GET") === method && url.includes(urlPart)
  );
}
