import { fakeResponse, mockFetch } from "./helpers.js";

// API simulada con estado para invitados, contactos, videos, participaciones y catálogos
// (pruebas de pantallas). `onRequest(url, options)` permite inyectar respuestas
// (p. ej. errores): si devuelve algo, se usa.
export function createFakeBackend({
  guests = [],
  contacts = [],
  videos = [],
  participations = [], // { id, guest_id, video_id, notes }
  guestCandidates = [], // ver STAGING_GUEST_CANDIDATE_DEFAULTS
  contactCandidates = [], // ver STAGING_CONTACT_CANDIDATE_DEFAULTS
  suggestions = [], // { video_id, program_name, host_names, status } (programa y conductores sugeridos)
  programHosts = {}, // { [program_id]: ["Nombre de conductor", ...] } (conductores ya registrados)
  // Resultado del botón "Ingesta" (POST /ingestion/runs): un objeto fijo, o una función
  // (body) => resultado para simular distintos conteos/errores según el batch_size pedido.
  // Por defecto: corrida exitosa que "proceso" todo el lote pedido, sin errores.
  ingestionRun,
  pageSize = 2,
  onRequest,
} = {}) {
  // Copia profunda: los PATCH de la API simulada modifican los objetos, y si fueran los mismos
  // que las constantes del archivo de pruebas, una prueba contaminaría a las siguientes.
  const db = {
    guests: structuredClone(guests),
    contacts: structuredClone(contacts),
    videos: structuredClone(videos),
    participations: structuredClone(participations),
    guestCandidates: structuredClone(guestCandidates),
    contactCandidates: structuredClone(contactCandidates),
    suggestions: structuredClone(suggestions),
    programHosts: structuredClone(programHosts),
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
      "contact-relationships": [
        { id: 1, name: "propio", is_active: true },
        { id: 2, name: "manager", is_active: true },
        { id: 3, name: "patrocinador", is_active: true },
      ],
      "video-types": [
        { id: 1, name: "Entrevista", is_active: true },
        { id: 2, name: "Evento", is_active: true },
      ],
      programs: [{ id: 1, name: "Buenos días", is_active: true }],
      hosts: [
        { id: 1, name: "Dante", is_active: true },
        { id: 2, name: "Mose Griffin", is_active: true },
      ],
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

  const videoSummary = (v) => ({ id: v.id, youtube_video_id: v.youtube_video_id, title: v.title, source: v.source });

  const guestCandidateOut = (c) => ({ ...c, video: videoSummary(db.videos.find((v) => v.id === c.video_id)) });
  const contactCandidateOut = (c) => ({ ...c, video: videoSummary(db.videos.find((v) => v.id === c.video_id)) });

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
      (m = pathname.match(/^\/(boroughs|guest-categories|contact-types|contact-relationships|video-types|programs|hosts)$/)) &&
      method === "GET"
    ) {
      return fakeResponse(200, db.catalogs[m[1]].filter((i) => i.is_active));
    }

    if (pathname === "/contact-types" && method === "POST") {
      const item = { id: db.nextId++, name: body.name, is_active: true };
      db.catalogs["contact-types"].push(item);
      return fakeResponse(201, item);
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
        const guestStatus = params.get("guest_status");
        let list = db.videos;
        if (source) list = list.filter((v) => v.source === source);
        if (guestStatus) list = list.filter((v) => v.guest_status === guestStatus);
        return fakeResponse(200, pageOf(list, params));
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

    // ---- Staging Review ----
    if (pathname === "/staging/guest-candidates" && method === "GET") {
      const status = params.get("status") || "pending";
      const list = db.guestCandidates.filter((c) => c.status === status);
      const page = pageOf(list, params);
      return fakeResponse(200, { ...page, items: page.items.map(guestCandidateOut) });
    }

    if ((m = pathname.match(/^\/staging\/guest-candidates\/(\d+)$/)) && method === "GET") {
      const candidate = db.guestCandidates.find((c) => c.id === Number(m[1]));
      if (!candidate) return fakeResponse(404, { detail: `No existe el candidato de invitado ${m[1]}` });
      return fakeResponse(200, guestCandidateOut(candidate));
    }

    if ((m = pathname.match(/^\/staging\/guest-candidates\/(\d+)\/suggestions$/)) && method === "GET") {
      const candidate = db.guestCandidates.find((c) => c.id === Number(m[1]));
      if (!candidate) return fakeResponse(404, { detail: `No existe el candidato de invitado ${m[1]}` });
      const key = candidate.extracted_name.toLowerCase();
      const matches = db.guests.filter(
        (g) => g.full_name.toLowerCase() === key || g.full_name.toLowerCase().includes(key) || key.includes(g.full_name.toLowerCase())
      );
      return fakeResponse(200, matches.map((g) => ({ id: g.id, full_name: g.full_name })));
    }

    if ((m = pathname.match(/^\/staging\/guest-candidates\/(\d+)\/accept$/)) && method === "POST") {
      const candidate = db.guestCandidates.find((c) => c.id === Number(m[1]));
      if (!candidate) return fakeResponse(404, { detail: `No existe el candidato de invitado ${m[1]}` });
      if (candidate.status !== "pending") return fakeResponse(409, { detail: "El candidato ya fue revisado" });

      let guest;
      if (body.existing_guest_id) {
        guest = db.guests.find((g) => g.id === body.existing_guest_id);
        if (!guest) return fakeResponse(404, { detail: `No existe el invitado ${body.existing_guest_id}` });
      } else {
        guest = guestFromPayload(body, db.nextId++);
        db.guests.push(guest);
      }
      if (!db.participations.some((p) => p.guest_id === guest.id && p.video_id === candidate.video_id)) {
        db.participations.push({ id: db.nextId++, guest_id: guest.id, video_id: candidate.video_id, notes: null });
      }
      candidate.status = "accepted";
      candidate.linked_guest_id = guest.id;
      candidate.reviewed_at = new Date().toISOString();
      return fakeResponse(200, guest);
    }

    if ((m = pathname.match(/^\/staging\/guest-candidates\/(\d+)\/reject$/)) && method === "POST") {
      const candidate = db.guestCandidates.find((c) => c.id === Number(m[1]));
      if (!candidate) return fakeResponse(404, { detail: `No existe el candidato de invitado ${m[1]}` });
      if (candidate.status !== "pending") return fakeResponse(409, { detail: "El candidato ya fue revisado" });
      candidate.status = "rejected";
      candidate.reviewed_at = new Date().toISOString();
      return fakeResponse(200, guestCandidateOut(candidate));
    }

    if (pathname === "/staging/contact-candidates" && method === "GET") {
      const status = params.get("status") || "pending";
      const doubtful = params.get("doubtful");
      const list = db.contactCandidates
        .filter((c) => c.status === status)
        .filter((c) => doubtful === null || Boolean(c.doubtful) === (doubtful === "true"));
      const page = pageOf(list, params);
      return fakeResponse(200, { ...page, items: page.items.map(contactCandidateOut) });
    }

    if ((m = pathname.match(/^\/staging\/contact-candidates\/(\d+)$/)) && method === "GET") {
      const candidate = db.contactCandidates.find((c) => c.id === Number(m[1]));
      if (!candidate) return fakeResponse(404, { detail: `No existe el candidato de contacto ${m[1]}` });
      return fakeResponse(200, contactCandidateOut(candidate));
    }

    if ((m = pathname.match(/^\/staging\/contact-candidates\/(\d+)\/accept$/)) && method === "POST") {
      const candidate = db.contactCandidates.find((c) => c.id === Number(m[1]));
      if (!candidate) return fakeResponse(404, { detail: `No existe el candidato de contacto ${m[1]}` });
      if (candidate.status !== "pending") return fakeResponse(409, { detail: "El candidato ya fue revisado" });
      const contact = {
        id: db.nextId++,
        guest_id: body.guest_id,
        contact_type: catalogItem("contact-types", body.contact_type_id),
        value: body.value,
        note: body.note ?? null,
        source: "video_description",
        verified: false,
        relationship: catalogItem("contact-relationships", body.relationship_id),
      };
      db.contacts.push(contact);
      candidate.status = "accepted";
      candidate.linked_contact_id = contact.id;
      candidate.reviewed_at = new Date().toISOString();
      return fakeResponse(200, contact);
    }

    if ((m = pathname.match(/^\/staging\/contact-candidates\/(\d+)\/reject$/)) && method === "POST") {
      const candidate = db.contactCandidates.find((c) => c.id === Number(m[1]));
      if (!candidate) return fakeResponse(404, { detail: `No existe el candidato de contacto ${m[1]}` });
      if (candidate.status !== "pending") return fakeResponse(409, { detail: "El candidato ya fue revisado" });
      candidate.status = "rejected";
      candidate.reviewed_at = new Date().toISOString();
      return fakeResponse(200, contactCandidateOut(candidate));
    }

    // ---- Revisión por video (se consideran "ingeridos" los videos con source "youtube") ----
    // Tipo del catálogo que corresponde a la pista (nombre igual o sinónimo habitual), como el backend.
    const typeSynonyms = { email: ["correo"], telefono: ["celular", "telefono"], url: ["sitio web", "web"] };
    const suggestedType = (hint) => {
      const names = [hint.toLowerCase(), ...(typeSynonyms[hint.toLowerCase()] ?? [])];
      for (const name of names) {
        const found = db.catalogs["contact-types"].find((t) => t.is_active && t.name.toLowerCase() === name);
        if (found) return found.id;
      }
      return null;
    };
    // Corto pendiente: menos de 60 s (0 cuenta; sin duración no) y aún sin revisar, como el backend.
    const isShortPending = (v) =>
      typeof v.duration_seconds === "number" && v.duration_seconds < 60 && v.guest_status === "pending";
    // Misma regla que el backend: de un par se conserva el que no tiene 📱 y, si son iguales, el de menor id.
    const isDuplicateCopy = (v) => {
      const original = db.videos.find((o) => o.id === v.possible_duplicate_of_video_id);
      if (!original) return false;
      const mobile = v.title.includes("📱");
      const originalMobile = original.title.includes("📱");
      return (mobile && !originalMobile) || (mobile === originalMobile && v.id > original.id);
    };
    const pendingGuests = (videoId) => db.guestCandidates.filter((c) => c.video_id === videoId && c.status === "pending");
    const pendingContacts = (videoId) => db.contactCandidates.filter((c) => c.video_id === videoId && c.status === "pending");
    const pendingSuggestion = (videoId) => db.suggestions.find((s) => s.video_id === videoId && (s.status ?? "pending") === "pending");
    const reviewFilters = {
      pending: (v) => pendingGuests(v.id).length > 0 || Boolean(pendingSuggestion(v.id)),
      with_contacts: (v) => pendingContacts(v.id).length > 0,
      doubtful_contacts: (v) => pendingContacts(v.id).some((c) => c.doubtful),
      no_candidates: (v) =>
        pendingGuests(v.id).length === 0 && pendingContacts(v.id).length === 0 && !pendingSuggestion(v.id) && v.guest_status === "pending",
      no_guests: (v) => v.guest_status === "no_guests",
      short: (v) => isShortPending(v),
      reviewed: (v) => v.guest_status === "has_guests",
      duplicates: (v) => isDuplicateCopy(v),
    };
    const reviewVideos = (filter, q) =>
      db.videos
        .filter(
          (v) =>
            v.source === "youtube" &&
            reviewFilters[filter](v) &&
            (filter === "duplicates" || !isDuplicateCopy(v)) &&
            (filter === "short" || !isShortPending(v)),
        )
        .filter((v) => !q || v.title.toLowerCase().includes(q.toLowerCase()));

    if (pathname === "/staging/review/counts" && method === "GET") {
      const q = params.get("q") || "";
      return fakeResponse(200, Object.fromEntries(Object.keys(reviewFilters).map((f) => [f, reviewVideos(f, q).length])));
    }

    if (pathname === "/staging/review/videos" && method === "GET") {
      const page = pageOf(reviewVideos(params.get("filter") || "pending", params.get("q") || ""), params);
      return fakeResponse(200, {
        ...page,
        items: page.items.map((v) => {
          const suggestion = pendingSuggestion(v.id);
          const suggestedProgram = suggestion?.program_name
            ? db.catalogs.programs.find((p) => p.name.toLowerCase() === suggestion.program_name.toLowerCase())
            : null;
          return {
            id: v.id,
            youtube_video_id: v.youtube_video_id,
            title: v.title,
            description: v.description ?? null,
            published_at: v.published_at ?? null,
            guest_status: v.guest_status,
            possible_duplicate_of_video_id: v.possible_duplicate_of_video_id ?? null,
            is_duplicate_copy: isDuplicateCopy(v),
            program_id: v.program?.id ?? null,
            suggested_program_id: suggestedProgram?.id ?? null,
            suggested_host_names: suggestion?.host_names ?? [],
            program_host_names: v.program ? db.programHosts[v.program.id] ?? [] : [],
            doubtful_names: suggestion?.doubtful_names ?? [],
            usual_host_names: [
              ...(suggestion?.usual_host_names ?? []),
              ...(db.programHosts[v.program?.id ?? suggestedProgram?.id] ?? []),
            ].filter((name, i, all) => all.indexOf(name) === i && !(suggestion?.host_names ?? []).includes(name)),
            guest_candidates: pendingGuests(v.id),
            contact_candidates: pendingContacts(v.id).map((c) => ({
              ...c,
              guest_candidate_id: c.guest_candidate_id ?? null,
              suggested_contact_type_id: suggestedType(c.type_hint),
            })),
            participants: db.participations
              .filter((p) => p.video_id === v.id)
              .map((p) => db.guests.find((g) => g.id === p.guest_id))
              .filter(Boolean)
              .map((g) => ({ id: g.id, full_name: g.full_name })),
          };
        }),
      });
    }

    if ((m = pathname.match(/^\/staging\/review\/videos\/(\d+)\/resolve$/)) && method === "POST") {
      const video = db.videos.find((v) => v.id === Number(m[1]));
      if (!video) return fakeResponse(404, { detail: `No existe el video ${m[1]}` });
      const guestsIn = body.guests ?? [];
      const rejectIds = body.reject_candidate_ids ?? [];
      const added = body.added_guests ?? [];
      if (body.no_guests && (guestsIn.length || added.length)) {
        return fakeResponse(422, { detail: "No se puede marcar 'sin invitados' y a la vez aceptar o agregar invitados" });
      }
      const hostNames = body.host_names ?? [];
      if (hostNames.length && !body.program_id && !video.program) {
        return fakeResponse(422, { detail: "Para guardar conductores elige primero el programa del video" });
      }
      const acceptedIds = [];
      const linkGuest = (name) => {
        let guest = db.guests.find((g) => g.full_name.toLowerCase() === name.toLowerCase());
        if (!guest) {
          guest = guestFromPayload({ full_name: name }, db.nextId++);
          db.guests.push(guest);
        }
        if (!db.participations.some((p) => p.guest_id === guest.id && p.video_id === video.id)) {
          db.participations.push({ id: db.nextId++, guest_id: guest.id, video_id: video.id, notes: null });
        }
        acceptedIds.push(guest.id);
        return guest.id;
      };
      const guestByCandidate = {};
      for (const item of guestsIn) {
        const candidate = db.guestCandidates.find((c) => c.id === item.candidate_id);
        if (!candidate) return fakeResponse(404, { detail: `No existe el candidato de invitado ${item.candidate_id}` });
        guestByCandidate[item.candidate_id] = linkGuest(item.full_name || candidate.extracted_name);
        candidate.status = "accepted";
      }
      for (const id of rejectIds) {
        const candidate = db.guestCandidates.find((c) => c.id === id);
        if (candidate) candidate.status = "rejected";
      }
      const guestByAdded = {};
      for (const item of added) guestByAdded[item.full_name.toLowerCase()] = linkGuest(item.full_name);
      // Contactos: se aceptan atribuidos a un invitado (candidato aceptado, agregado o existente).
      const acceptedContactIds = [];
      for (const item of body.contacts ?? []) {
        const candidate = db.contactCandidates.find((c) => c.id === item.candidate_id);
        if (!candidate) return fakeResponse(404, { detail: `No existe el candidato de contacto ${item.candidate_id}` });
        const guestId =
          item.guest_candidate_id != null
            ? guestByCandidate[item.guest_candidate_id]
            : item.added_guest_name != null
              ? guestByAdded[item.added_guest_name.toLowerCase()]
              : item.existing_guest_id;
        if (!guestId) return fakeResponse(422, { detail: "El contacto apunta a un invitado que no se registra" });
        const contact = {
          id: db.nextId++,
          guest_id: guestId,
          contact_type: catalogItem("contact-types", item.contact_type_id),
          value: item.value ?? candidate.value,
          note: null,
          source: "video_description",
          verified: false,
          relationship: catalogItem("contact-relationships", item.relationship_id),
        };
        db.contacts.push(contact);
        candidate.status = "accepted";
        candidate.linked_contact_id = contact.id;
        acceptedContactIds.push(contact.id);
      }
      for (const id of body.reject_contact_ids ?? []) {
        const candidate = db.contactCandidates.find((c) => c.id === id);
        if (candidate) candidate.status = "rejected";
      }
      let rejected = rejectIds.length;
      if (body.no_guests) {
        for (const candidate of pendingGuests(video.id)) {
          candidate.status = "rejected";
          rejected += 1;
        }
        video.guest_status = "no_guests";
      } else if (acceptedIds.length) {
        video.guest_status = "has_guests";
      }
      if (body.program_id) video.program = catalogItem("programs", body.program_id);
      const hostIds = [];
      for (const name of hostNames) {
        let host = db.catalogs.hosts.find((h) => h.name.toLowerCase() === name.toLowerCase());
        if (!host) {
          host = { id: db.nextId++, name, is_active: true };
          db.catalogs.hosts.push(host);
        }
        hostIds.push(host.id);
        const linked = (db.programHosts[video.program.id] ??= []);
        if (!linked.includes(host.name)) linked.push(host.name);
      }
      const suggestion = pendingSuggestion(video.id);
      if (suggestion) suggestion.status = body.program_id || hostNames.length ? "accepted" : "rejected";
      return fakeResponse(200, {
        video_id: video.id, guest_status: video.guest_status, accepted_guest_ids: acceptedIds,
        rejected_count: rejected, program_id: video.program?.id ?? null, host_ids: hostIds,
        accepted_contact_ids: acceptedContactIds, rejected_contact_count: (body.reject_contact_ids ?? []).length,
      });
    }

    // ---- Ingesta ----
    if (pathname === "/ingestion/runs" && method === "POST") {
      if (typeof ingestionRun === "function") return fakeResponse(201, ingestionRun(body));
      if (ingestionRun) return fakeResponse(201, ingestionRun);
      const batchSize = body.batch_size ?? 30;
      return fakeResponse(201, {
        id: db.nextId++,
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
        status: "completed",
        trigger: "manual",
        requested_batch_size: batchSize,
        processed_count: batchSize,
        success_count: batchSize,
        error_count: 0,
        errors: [],
      });
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
