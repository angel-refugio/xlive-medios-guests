import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Pager from "../../components/Pager.jsx";
import { useCatalog } from "../../hooks/useCatalog.js";
import { dateOnly, youtubeUrl } from "../videos/labels.js";
import { canCreateTypeFrom, confidencePercent, matchRelationshipId, sameName, typeNameFromHint } from "./labels.js";

// Los filtros de la barra superior; cada uno muestra cuántos videos tiene.
const FILTERS = [
  { key: "pending", label: "Pendientes", empty: "No hay videos con invitados candidatos por revisar." },
  { key: "with_contacts", label: "Con contactos", empty: "No hay videos con contactos candidatos por revisar." },
  { key: "doubtful_contacts", label: "Contactos dudosos", empty: "No hay videos con contactos dudosos por revisar." },
  { key: "no_candidates", label: "Sin candidatos", empty: "No hay videos sin candidatos." },
  { key: "no_guests", label: "Sin invitados", empty: 'No hay videos marcados "sin invitados".' },
  // Posibles intros: salen de Pendientes y de los demás filtros hasta que se revisan aquí.
  { key: "short", label: "Cortos (< 1 min)", empty: "No hay videos cortos por revisar." },
  // Avance: videos con invitados ya aceptados (se corrigen desde la ficha de cada invitado).
  { key: "reviewed", label: "Revisados", empty: "Todavía no hay videos revisados con invitados." },
];

const cleanName = (text) => text.trim().replace(/\s+/g, " ");
const hasName = (list, name) => list.some((n) => n.toLowerCase() === name.toLowerCase());

// Revisión por video: cada video es una tarjeta con su texto original a la izquierda y, a la
// derecha, el programa, los conductores y los invitados editables. "Correcto" acepta todo de
// una vez; se puede corregir un nombre, quitar uno que no es persona, o agregar uno que la
// extracción no encontró.
export default function ReviewByVideo() {
  const [params, setParams] = useSearchParams();
  const filter = FILTERS.some((f) => f.key === params.get("filter")) ? params.get("filter") : "pending";
  const q = params.get("q") || "";
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [searchText, setSearchText] = useState(q);
  const [data, setData] = useState(null);
  const [counts, setCounts] = useState(null);
  const [error, setError] = useState("");
  const programs = useCatalog("programs");
  const hosts = useCatalog("hosts");
  const contactTypes = useCatalog("contact-types");
  const relationships = useCatalog("contact-relationships");

  const load = useCallback(() => {
    setError("");
    return Promise.all([
      api.get("/staging/review/videos", { filter, q, page }),
      api.get("/staging/review/counts", { q }),
    ])
      .then(([videos, totals]) => {
        setData(videos);
        setCounts(totals);
      })
      .catch((err) => {
        console.error("[pages.staging.ReviewByVideo.load] No se pudo cargar la revisión:", err);
        setError(err.message);
      });
  }, [filter, q, page]);

  useEffect(() => {
    setData(null);
    load();
  }, [load]);

  const update = (next) => {
    const merged = { filter, q, page: 1, ...next };
    const clean = {};
    if (merged.filter !== "pending") clean.filter = merged.filter;
    if (merged.q) clean.q = merged.q;
    if (Number(merged.page) > 1) clean.page = String(merged.page);
    setParams(clean);
  };

  function submitSearch(event) {
    event.preventDefault();
    update({ q: searchText.trim() });
  }

  const current = FILTERS.find((f) => f.key === filter);

  return (
    <div className="review">
      <div className="review-bar">
        <div className="filter-chips" role="group" aria-label="Filtros de revisión">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className="filter-chip"
              aria-pressed={f.key === filter}
              onClick={() => update({ filter: f.key })}
            >
              {f.label}
              {counts && <span className="count">{counts[f.key]}</span>}
            </button>
          ))}
        </div>
        <form className="review-search" onSubmit={submitSearch} role="search">
          <input
            type="search"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Buscar por título"
            aria-label="Buscar por título"
          />
          <button type="submit">Buscar</button>
        </form>
      </div>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!data && !error && <p className="muted">Cargando…</p>}
      {data && data.total === 0 && <p className="muted">{current.empty}</p>}

      {data?.items?.map((video) => (
        <VideoReviewCard
          key={video.id}
          video={video}
          programs={programs.items}
          hosts={hosts.items}
          contactTypes={contactTypes.items}
          relationships={relationships.items}
          onTypeCreated={contactTypes.reload}
          onResolved={load}
        />
      ))}

      {data && data.total > 0 && (
        <Pager page={page} pageSize={data.page_size} total={data.total} noun="videos" onPage={(n) => update({ page: n })} />
      )}
    </div>
  );
}

// Invitado de la tarjeta al que la IA asignó el contacto, como referencia del selector:
// `cand:<id>` (candidato de invitado), `guest:<id>` (ya participa en el video) o "" (sin asignar).
function initialGuestRef(contact, video) {
  const candidate =
    video.guest_candidates.find((g) => g.id === contact.guest_candidate_id) ??
    (contact.guest_name ? video.guest_candidates.find((g) => sameName(g.extracted_name, contact.guest_name)) : null);
  if (candidate) return `cand:${candidate.id}`;
  const participant = contact.guest_name ? video.participants?.find((p) => sameName(p.full_name, contact.guest_name)) : null;
  return participant ? `guest:${participant.id}` : "";
}

// `cand:7` -> { guest_candidate_id: 7 }; `added:Ana` -> { added_guest_name: "Ana" }; `guest:3` -> { existing_guest_id: 3 }
function guestReference(ref) {
  const [kind, ...rest] = ref.split(":");
  const value = rest.join(":");
  if (kind === "cand") return { guest_candidate_id: Number(value) };
  if (kind === "added") return { added_guest_name: value };
  return { existing_guest_id: Number(value) };
}

function VideoReviewCard({ video, programs, hosts, contactTypes, relationships, onTypeCreated, onResolved }) {
  // Cada candidato es una fila editable; "Quitar" lo marca para rechazarlo.
  const [rows, setRows] = useState(() =>
    video.guest_candidates.map((c) => ({ candidate: c, name: c.extracted_name, removed: false }))
  );
  const [added, setAdded] = useState([]);
  const [newName, setNewName] = useState("");
  // El programa del video, o el que sugiere la ingesta; los conductores sugeridos son del programa.
  const [programId, setProgramId] = useState(String(video.program_id ?? video.suggested_program_id ?? ""));
  const [hostNames, setHostNames] = useState(video.suggested_host_names);
  const [newHost, setNewHost] = useState("");
  // Nombres que la ingesta no pudo clasificar: el humano decide "→ invitado" o "→ conductor".
  const [doubtful, setDoubtful] = useState(video.doubtful_names ?? []);
  // Contactos del video: se aceptan (con tipo, invitado y relación) o se descartan. Los dudosos, o
  // sin invitado, empiezan desmarcados: hay que marcarlos a propósito.
  const [contactRows, setContactRows] = useState(() =>
    video.contact_candidates.map((c) => {
      const ref = initialGuestRef(c, video);
      return {
        candidate: c,
        accept: !c.doubtful && ref !== "",
        typeId: c.suggested_contact_type_id ? String(c.suggested_contact_type_id) : "",
        relationshipId: null,   // null = la que propuso la IA, cuando el catálogo ya cargó
        ref,
      };
    })
  );
  // Contactos que se capturan a mano (los que se ven dentro del video, no en el título ni la descripción).
  const [addedContacts, setAddedContacts] = useState([]);
  const [newContact, setNewContact] = useState({ typeId: "", value: "", relationshipId: "", ref: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const keptRows = rows.filter((r) => !r.removed);
  const removedRows = rows.filter((r) => r.removed);
  const hasGuests = keptRows.length + added.length > 0;
  const canDiscard = !hasGuests && removedRows.length > 0;
  const hasMeta = Boolean(programId) || hostNames.length > 0;
  const hostsWithoutProgram = hostNames.length > 0 && !programId;

  // Invitados a los que se puede asignar un contacto: los que se conservan, los agregados a mano y
  // los que ya participan en el video.
  const guestOptions = [
    ...keptRows.map((r) => ({ value: `cand:${r.candidate.id}`, label: r.name.trim() || r.candidate.extracted_name })),
    ...added.map((name) => ({ value: `added:${name}`, label: name })),
    ...(video.participants ?? []).map((p) => ({ value: `guest:${p.id}`, label: `${p.full_name} (ya registrado)` })),
  ];
  const validRefs = new Set(guestOptions.map((o) => o.value));
  // Un contacto apuntado a un invitado que se quitó queda sin asignar.
  const refOf = (row) => (validRefs.has(row.ref) ? row.ref : "");
  const relationshipOf = (row) => row.relationshipId ?? matchRelationshipId(relationships, row.candidate.relationship_name);

  function setContact(index, patch) {
    setContactRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  // Crear un tipo de contacto nuevo lo decide quien revisa, con un clic (la IA nunca lo crea sola).
  async function createType(index) {
    setError("");
    setBusy(true);
    try {
      const created = await api.post("/contact-types", { name: typeNameFromHint(contactRows[index].candidate.type_hint) });
      setContact(index, { typeId: String(created.id) });
      onTypeCreated();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function addContact() {
    const value = newContact.value.trim();
    if (!newContact.typeId || !value || !validRefs.has(newContact.ref)) {
      setError("Para agregar un contacto elige el tipo y el invitado, y escribe el valor");
      return;
    }
    setError("");
    setAddedContacts((prev) => [...prev, { ...newContact, value }]);
    setNewContact({ typeId: "", value: "", relationshipId: "", ref: newContact.ref });   // suelen ser varios del mismo invitado
  }

  // Decisión sobre los contactos; null (con el error mostrado) si falta tipo o invitado en alguno aceptado.
  function contactsPayload() {
    const extra = {};
    if (addedContacts.length > 0) {
      if (addedContacts.some((c) => !validRefs.has(c.ref))) {
        setError("Un contacto agregado apunta a un invitado que quitaste: quítalo o vuelve a agregar al invitado");
        return null;
      }
      extra.added_contacts = addedContacts.map((c) => ({
        contact_type_id: Number(c.typeId),
        value: c.value,
        ...(c.relationshipId ? { relationship_id: Number(c.relationshipId) } : {}),
        ...guestReference(c.ref),
      }));
    }
    if (contactRows.length === 0) return extra;
    const accepted = contactRows.filter((r) => r.accept);
    if (accepted.some((r) => !r.typeId || !refOf(r))) {
      setError("Elige el tipo y el invitado de cada contacto que aceptas");
      return null;
    }
    return {
      ...extra,
      contacts: accepted.map((r) => {
        const relationshipId = relationshipOf(r);
        return {
          candidate_id: r.candidate.id,
          contact_type_id: Number(r.typeId),
          ...(relationshipId ? { relationship_id: Number(relationshipId) } : {}),
          ...guestReference(refOf(r)),
        };
      }),
      reject_contact_ids: contactRows.filter((r) => !r.accept).map((r) => r.candidate.id),
    };
  }

  function setName(index, name) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, name } : r)));
  }

  function setRemoved(index, removed) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, removed } : r)));
  }

  function addGuest() {
    const name = cleanName(newName);
    if (!name) return;
    if (!hasName(added, name)) setAdded((prev) => [...prev, name]);
    setNewName("");
  }

  function addHost() {
    const name = cleanName(newHost);
    if (!name) return;
    if (!hasName(hostNames, name)) setHostNames((prev) => [...prev, name]);
    setNewHost("");
  }

  const usualHosts = (video.usual_host_names ?? []).filter((n) => !hasName(hostNames, n));

  function addUsualHost(name) {
    if (!hasName(hostNames, name)) setHostNames((prev) => [...prev, name]);
  }

  function promoteToGuest(name) {
    if (!hasName(added, name)) setAdded((prev) => [...prev, name]);
    setDoubtful((prev) => prev.filter((d) => d.name !== name));
  }

  function promoteToHost(name) {
    if (!hasName(hostNames, name)) setHostNames((prev) => [...prev, name]);
    setDoubtful((prev) => prev.filter((d) => d.name !== name));
  }

  // Lo que se revisó del programa y los conductores viaja en toda resolución del video.
  function metaPayload() {
    const meta = {};
    if (programId) meta.program_id = Number(programId);
    if (hostNames.length) meta.host_names = hostNames;
    return meta;
  }

  async function send(body) {
    setError("");
    setBusy(true);
    try {
      await api.post(`/staging/review/videos/${video.id}/resolve`, body);
      await onResolved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function approve() {
    if (keptRows.some((r) => !r.name.trim())) {
      setError("Ningún invitado puede quedar sin nombre");
      return;
    }
    const contacts = contactsPayload();
    if (contacts === null) return;
    send({
      ...contacts,
      guests: keptRows.map((r) => {
        const name = cleanName(r.name);
        const item = { candidate_id: r.candidate.id };
        if (name !== r.candidate.extracted_name) item.full_name = name;
        return item;
      }),
      reject_candidate_ids: removedRows.map((r) => r.candidate.id),
      added_guests: added.map((full_name) => ({ full_name })),
      ...metaPayload(),
    });
  }

  const markNoGuests = () => send({ no_guests: true, ...metaPayload() });

  const primaryLabel = hasGuests
    ? "Correcto"
    : canDiscard
      ? "Descartar candidatos"
      : hasMeta
        ? "Guardar programa y conductores"
        : contactRows.length > 0 || addedContacts.length > 0
          ? "Guardar contactos"
          : null;

  return (
    <article className="review-card" aria-label={video.title}>
      <div className="review-text">
        <h3>{video.title}</h3>
        <p className="muted">
          <a href={youtubeUrl(video.youtube_video_id)} target="_blank" rel="noopener noreferrer">
            Ver en YouTube
          </a>{" "}
          · {dateOnly(video.published_at) || "sin fecha"} · <Link to={`/videos/${video.id}`}>Abrir video</Link>
        </p>
        {video.description ? (
          <details>
            <summary>Descripción</summary>
            <pre className="description">{video.description}</pre>
          </details>
        ) : (
          <p className="muted">Sin descripción.</p>
        )}
      </div>

      <div className="review-fields">
        <div className="program-field">
          <label>
            Programa
            <select aria-label="Programa" value={programId} onChange={(e) => setProgramId(e.target.value)} disabled={busy}>
              <option value="">— Sin programa —</option>
              {programs.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          {!video.program_id && video.suggested_program_id && programId === String(video.suggested_program_id) && (
            <small className="muted">Sugerido por la ingesta</small>
          )}
        </div>

        <div className="hosts-field">
          <strong>Conductores</strong>
          {hostNames.length > 0 && (
            <ul className="chips" aria-label="Conductores">
              {hostNames.map((name) => (
                <li key={name}>
                  {name}{" "}
                  <button type="button" aria-label={`Quitar conductor ${name}`} onClick={() => setHostNames((prev) => prev.filter((n) => n !== name))} disabled={busy}>
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          {usualHosts.length > 0 && (
            <div className="usual-hosts">
              <small className="muted">Conductores habituales del programa:</small>
              {usualHosts.map((name) => (
                <button key={name} type="button" className="quick" aria-label={`Agregar ${name} como conductor`} onClick={() => addUsualHost(name)} disabled={busy}>
                  + {name}
                </button>
              ))}
            </div>
          )}
          <div className="inline-form">
            <label>
              Agregar conductor
              <input
                list={`hosts-${video.id}`}
                value={newHost}
                onChange={(e) => setNewHost(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addHost();
                  }
                }}
                maxLength={150}
                disabled={busy}
              />
            </label>
            <datalist id={`hosts-${video.id}`}>
              {hosts.map((h) => (
                <option key={h.id} value={h.name} />
              ))}
            </datalist>
            <button type="button" onClick={addHost} disabled={busy || !newHost.trim()}>
              Agregar conductor
            </button>
          </div>
          {hostsWithoutProgram && <small className="warn-text">Elige un programa para guardar los conductores (son del programa).</small>}
        </div>

        {doubtful.length > 0 && (
          <div className="doubtful-field">
            <strong>Dudosos</strong>
            <small className="muted">Nombres que no pude clasificar: elige qué son.</small>
            <ul className="doubtful-list" aria-label="Dudosos">
              {doubtful.map((d) => (
                <li key={d.name}>
                  <span className="doubtful-name">{d.name}</span>
                  {d.guess !== "unknown" && <small className="muted">la IA cree: {d.guess === "host" ? "conductor" : "invitado"}</small>}
                  <button type="button" className="quick" aria-label={`${d.name} → invitado`} onClick={() => promoteToGuest(d.name)} disabled={busy}>
                    → invitado
                  </button>
                  <button type="button" className="quick" aria-label={`${d.name} → conductor`} onClick={() => promoteToHost(d.name)} disabled={busy}>
                    → conductor
                  </button>
                  <button type="button" aria-label={`Descartar ${d.name}`} onClick={() => setDoubtful((prev) => prev.filter((x) => x.name !== d.name))} disabled={busy}>
                    Descartar
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        <strong>Invitados</strong>
        {(video.participants ?? []).length > 0 && (
          <div className="registered-guests">
            <small className="muted">Ya registrados en este video:</small>
            <ul className="chips" aria-label="Invitados registrados">
              {video.participants.map((p) => (
                <li key={p.id}>
                  <Link to={`/guests/${p.id}`}>{p.full_name}</Link>
                </li>
              ))}
            </ul>
          </div>
        )}
        {rows.length === 0 && added.length === 0 && (video.participants ?? []).length === 0 && (
          <p className="muted">La extracción no encontró invitados.</p>
        )}
        <ul className="guest-rows">
          {rows.map((row, index) => (
            <li key={row.candidate.id} className={row.removed ? "guest-row removed" : "guest-row"}>
              <input
                value={row.name}
                onChange={(e) => setName(index, e.target.value)}
                disabled={row.removed || busy}
                maxLength={255}
                aria-label={`Nombre de ${row.candidate.extracted_name}`}
              />
              <small className="muted">
                {confidencePercent(row.candidate.adjusted_confidence)}
                {row.candidate.is_possible_group && " · posible grupo"}
                {row.candidate.category_match && ` · ${row.candidate.category_match}`}
              </small>
              {row.removed ? (
                <button type="button" onClick={() => setRemoved(index, false)} disabled={busy}>
                  Restaurar {row.candidate.extracted_name}
                </button>
              ) : (
                <button type="button" aria-label={`Quitar ${row.candidate.extracted_name}`} onClick={() => setRemoved(index, true)} disabled={busy}>
                  Quitar
                </button>
              )}
            </li>
          ))}
          {added.map((name) => (
            <li key={`added-${name}`} className="guest-row">
              <span className="added-name">{name}</span>
              <small className="muted">agregado a mano</small>
              <button type="button" aria-label={`Quitar ${name}`} onClick={() => setAdded((prev) => prev.filter((n) => n !== name))} disabled={busy}>
                Quitar
              </button>
            </li>
          ))}
        </ul>

        <div className="inline-form">
          <label>
            Agregar invitado
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addGuest();
                }
              }}
              maxLength={255}
              disabled={busy}
            />
          </label>
          <button type="button" onClick={addGuest} disabled={busy || !newName.trim()}>
            Agregar
          </button>
        </div>

        {contactRows.length > 0 && (
          <div className="contacts-field">
            <strong>Contactos</strong>
            <small className="muted">
              Marca «Aceptar» en los correctos. Los dudosos empiezan sin marcar; los que queden sin marcar se
              descartan al guardar.
            </small>
            <ul className="contact-list" aria-label="Contactos del video">
              {contactRows.map((row, index) => {
                const c = row.candidate;
                return (
                  <li key={c.id} className={row.accept ? "contact-row-card" : "contact-row-card off"}>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={row.accept}
                        aria-label={`Aceptar contacto ${c.value}`}
                        onChange={(e) => setContact(index, { accept: e.target.checked })}
                        disabled={busy}
                      />
                      <span className="contact-value">
                        <strong>{c.type_hint}:</strong> {c.value}
                      </span>
                    </label>
                    {c.doubtful && (
                      <span className="badge warn" title={c.doubtful_reason || undefined}>
                        Dudoso{c.doubtful_reason ? `: ${c.doubtful_reason}` : ""}
                      </span>
                    )}
                    <div className="contact-selects">
                      <select
                        aria-label={`Tipo de ${c.value}`}
                        value={row.typeId}
                        onChange={(e) => setContact(index, { typeId: e.target.value })}
                        disabled={busy}
                      >
                        <option value="">— Tipo —</option>
                        {contactTypes.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name}
                          </option>
                        ))}
                      </select>
                      <select
                        aria-label={`Invitado de ${c.value}`}
                        value={refOf(row)}
                        onChange={(e) => setContact(index, { ref: e.target.value })}
                        disabled={busy}
                      >
                        <option value="">— Sin asignar —</option>
                        {guestOptions.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                      <select
                        aria-label={`Relación de ${c.value}`}
                        value={relationshipOf(row)}
                        onChange={(e) => setContact(index, { relationshipId: e.target.value })}
                        disabled={busy}
                      >
                        <option value="">— Relación —</option>
                        {relationships.map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.name}
                          </option>
                        ))}
                      </select>
                      {!row.typeId && canCreateTypeFrom(c.type_hint) && (
                        <button type="button" className="quick" onClick={() => createType(index)} disabled={busy}>
                          + Crear tipo «{typeNameFromHint(c.type_hint)}»
                        </button>
                      )}
                    </div>
                    {!row.accept && <small className="muted">Se descartará al guardar</small>}
                    {c.evidence && <blockquote className="evidence">{c.evidence}</blockquote>}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        <div className="add-contact contacts-field">
          <strong>Agregar contacto</strong>
          <small className="muted">Para un contacto que ves dentro del video (no está en el título ni en la descripción).</small>
          <div className="contact-selects">
            <select
              aria-label="Tipo del contacto nuevo"
              value={newContact.typeId}
              onChange={(e) => setNewContact((prev) => ({ ...prev, typeId: e.target.value }))}
              disabled={busy}
            >
              <option value="">— Tipo —</option>
              {contactTypes.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
            <input
              aria-label="Valor del contacto nuevo"
              placeholder="Valor (teléfono, correo, @usuario…)"
              value={newContact.value}
              onChange={(e) => setNewContact((prev) => ({ ...prev, value: e.target.value }))}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addContact();
                }
              }}
              maxLength={500}
              disabled={busy}
            />
            <select
              aria-label="Invitado del contacto nuevo"
              value={validRefs.has(newContact.ref) ? newContact.ref : ""}
              onChange={(e) => setNewContact((prev) => ({ ...prev, ref: e.target.value }))}
              disabled={busy}
            >
              <option value="">— Invitado —</option>
              {guestOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <select
              aria-label="Relación del contacto nuevo"
              value={newContact.relationshipId}
              onChange={(e) => setNewContact((prev) => ({ ...prev, relationshipId: e.target.value }))}
              disabled={busy}
            >
              <option value="">— Relación —</option>
              {relationships.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
            <button type="button" onClick={addContact} disabled={busy}>
              Agregar contacto
            </button>
          </div>
          {addedContacts.length > 0 && (
            <ul className="chips" aria-label="Contactos agregados">
              {addedContacts.map((c, index) => (
                <li key={`${c.ref}-${c.typeId}-${c.value}`}>
                  <strong>{contactTypes.find((t) => String(t.id) === c.typeId)?.name}:</strong> {c.value} ·{" "}
                  {guestOptions.find((o) => o.value === c.ref)?.label ?? "invitado quitado"}{" "}
                  <button
                    type="button"
                    aria-label={`Quitar contacto ${c.value}`}
                    onClick={() => setAddedContacts((prev) => prev.filter((_, i) => i !== index))}
                    disabled={busy}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="form-actions">
          {primaryLabel && (
            <button type="button" className="primary" onClick={approve} disabled={busy || hostsWithoutProgram}>
              {primaryLabel}
            </button>
          )}
          {video.guest_status === "pending" && (
            <button type="button" onClick={markNoGuests} disabled={busy || added.length > 0 || addedContacts.length > 0 || hostsWithoutProgram}>
              Sin invitados
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
