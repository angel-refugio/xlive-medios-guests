import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Pager from "../../components/Pager.jsx";
import { useCatalog } from "../../hooks/useCatalog.js";
import { CANDIDATE_STATUS_LABELS, EXTRACTION_METHOD_LABELS, confidencePercent } from "./labels.js";

// Cola de contactos candidatos. El invitado al que se atribuyen siempre lo elige quien revisa.
export default function ContactCandidateQueue() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const status = params.get("status") || "pending";
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const [guests, setGuests] = useState([]);
  const contactTypes = useCatalog("contact-types");

  const load = useCallback(() => {
    setData(null);
    setError("");
    return api
      .get("/staging/contact-candidates", { page, status })
      .then(setData)
      .catch((err) => {
        console.error("[pages.staging.ContactCandidateQueue.load] No se pudo cargar la cola:", err);
        setError(err.message);
      });
  }, [page, status]);

  useEffect(() => {
    load();
  }, [load]);

  // Para elegir a quién se le atribuye el contacto al aceptar.
  useEffect(() => {
    api
      .get("/guests", { page_size: 200 })
      .then((result) => setGuests(result.items))
      .catch((err) => console.error("[pages.staging.ContactCandidateQueue] No se pudo cargar la lista de invitados:", err));
  }, []);

  const update = (next) => {
    const merged = { page: String(page), status, ...next };
    const clean = { status: merged.status };
    if (Number(merged.page) > 1) clean.page = String(merged.page);
    setParams(clean);
  };

  async function afterReview() {
    setExpandedId(null);
    await load();
  }

  return (
    <div className="card-wide">
      <label className="filter">
        Estado
        <select value={status} onChange={(e) => update({ status: e.target.value, page: 1 })}>
          {Object.entries(CANDIDATE_STATUS_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!data && !error && <p className="muted">Cargando…</p>}
      {data && data.total === 0 && <p className="muted">No hay candidatos en estado «{CANDIDATE_STATUS_LABELS[status]}».</p>}

      <ul className="item-list">
        {data?.items?.map((candidate) => (
          <li key={candidate.id} className="candidate-row">
            <div className="item-name">
              <strong>{candidate.type_hint}:</strong> {candidate.value}{" "}
              <span className="muted">
                · {EXTRACTION_METHOD_LABELS[candidate.extraction_method] || candidate.extraction_method} ·{" "}
                confianza {confidencePercent(candidate.raw_confidence)}
              </span>
              <br />
              <small className="muted">
                En video: <Link to={`/videos/${candidate.video.id}`}>{candidate.video.title}</Link>
              </small>
            </div>
            {status === "pending" && (
              <div className="item-actions">
                <button
                  type="button"
                  onClick={() => setExpandedId(expandedId === candidate.id ? null : candidate.id)}
                >
                  {expandedId === candidate.id ? "Cerrar" : "Revisar"}
                </button>
              </div>
            )}
            {expandedId === candidate.id && (
              <ContactCandidateReview
                candidate={candidate}
                guests={guests}
                contactTypes={contactTypes.items}
                onDone={afterReview}
                onCancel={() => setExpandedId(null)}
              />
            )}
          </li>
        ))}
      </ul>

      {data && data.total > 0 && (
        <Pager page={page} pageSize={data.page_size} total={data.total} noun="candidatos" onPage={(n) => update({ page: n })} />
      )}
    </div>
  );
}

function ContactCandidateReview({ candidate, guests, contactTypes, onDone, onCancel }) {
  const base = `/staging/contact-candidates/${candidate.id}`;
  const [guestId, setGuestId] = useState("");
  const [contactTypeId, setContactTypeId] = useState("");
  const [value, setValue] = useState(candidate.value);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function accept(event) {
    event.preventDefault();
    setError("");
    if (!guestId) {
      setError("Elige a qué invitado pertenece el contacto");
      return;
    }
    if (!contactTypeId) {
      setError("Elige el tipo de contacto");
      return;
    }
    if (!value.trim()) {
      setError("El valor del contacto es obligatorio");
      return;
    }
    setBusy(true);
    try {
      await api.post(`${base}/accept`, {
        guest_id: Number(guestId),
        contact_type_id: Number(contactTypeId),
        value: value.trim(),
        note: note.trim() || null,
      });
      await onDone();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  async function reject() {
    setError("");
    setBusy(true);
    try {
      await api.post(`${base}/reject`);
      await onDone();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={accept} className="candidate-review form-grid" aria-label={`Revisar contacto ${candidate.value}`}>
      <label>
        Invitado
        <select value={guestId} onChange={(e) => setGuestId(e.target.value)}>
          <option value="">— Elige un invitado —</option>
          {guests.map((g) => (
            <option key={g.id} value={g.id}>
              {g.full_name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Tipo de contacto
        <select value={contactTypeId} onChange={(e) => setContactTypeId(e.target.value)}>
          <option value="">— Elige un tipo —</option>
          {contactTypes.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Valor
        <input value={value} onChange={(e) => setValue(e.target.value)} maxLength={500} />
      </label>
      <label>
        Nota
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      </label>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="form-actions">
        <button type="submit" disabled={busy}>
          Aceptar contacto
        </button>
        <button type="button" onClick={reject} className="danger" disabled={busy}>
          Rechazar candidato
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          Cancelar
        </button>
      </div>
    </form>
  );
}
