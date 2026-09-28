import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Pager from "../../components/Pager.jsx";
import { useCatalog } from "../../hooks/useCatalog.js";
import { CANDIDATE_STATUS_LABELS, EXTRACTION_METHOD_LABELS, confidencePercent } from "./labels.js";

// Cola de invitados candidatos: aceptar (crea o vincula), editar antes de aceptar, o rechazar.
export default function GuestCandidateQueue() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const status = params.get("status") || "pending";
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const boroughs = useCatalog("boroughs");
  const categories = useCatalog("guest-categories");

  const load = useCallback(() => {
    setData(null);
    setError("");
    return api
      .get("/staging/guest-candidates", { page, status })
      .then(setData)
      .catch((err) => {
        console.error("[pages.staging.GuestCandidateQueue.load] No se pudo cargar la cola:", err);
        setError(err.message);
      });
  }, [page, status]);

  useEffect(() => {
    load();
  }, [load]);

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
              <strong>{candidate.extracted_name}</strong>{" "}
              <span className="muted">
                · {EXTRACTION_METHOD_LABELS[candidate.extraction_method] || candidate.extraction_method} ·{" "}
                confianza {confidencePercent(candidate.adjusted_confidence)}
              </span>
              {candidate.is_possible_group && <em> · posible grupo, no persona</em>}
              {candidate.category_match && (
                <em>
                  {" "}
                  · categoría: {candidate.category_match}
                  {candidate.category_is_new_suggestion && " (nueva)"}
                </em>
              )}
              <br />
              <small className="muted">
                En video: <Link to={`/videos/${candidate.video.id}`}>{candidate.video.title}</Link>
              </small>
              <br />
              <small className="muted">Evidencia: «{candidate.evidence}»</small>
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
              <GuestCandidateReview
                candidate={candidate}
                boroughs={boroughs.items}
                categories={categories.items}
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

function GuestCandidateReview({ candidate, boroughs, categories, onDone, onCancel }) {
  const base = `/staging/guest-candidates/${candidate.id}`;
  const [suggestions, setSuggestions] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .get(`${base}/suggestions`)
      .then((items) => {
        if (!cancelled) setSuggestions(items);
      })
      .catch((err) => console.error("[pages.staging.GuestCandidateReview] No se pudieron cargar sugerencias:", err));
    return () => {
      cancelled = true;
    };
  }, [base]);

  const [full_name, setFullName] = useState(candidate.extracted_name);
  const [organization, setOrganization] = useState("");
  const [role, setRole] = useState("");
  const [approx_age, setApproxAge] = useState("");
  const [borough_id, setBoroughId] = useState("");
  const [notes, setNotes] = useState("");
  const [categoryIds, setCategoryIds] = useState([]);
  const [newCategories, setNewCategories] = useState([]);
  const [newCategoryInput, setNewCategoryInput] = useState("");

  function toggleCategory(id) {
    setCategoryIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function addNewCategory() {
    const name = newCategoryInput.trim().replace(/\s+/g, " ");
    if (!name) return;
    if (!newCategories.some((n) => n.toLowerCase() === name.toLowerCase())) {
      setNewCategories((prev) => [...prev, name]);
    }
    setNewCategoryInput("");
  }

  async function acceptExisting(guestId) {
    setError("");
    setBusy(true);
    try {
      await api.post(`${base}/accept`, { existing_guest_id: guestId });
      await onDone();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  async function submitNew(event) {
    event.preventDefault();
    setError("");
    if (!full_name.trim()) {
      setError("El nombre es obligatorio");
      return;
    }
    setBusy(true);
    try {
      await api.post(`${base}/accept`, {
        full_name: full_name.trim(),
        organization: organization.trim() || null,
        role: role.trim() || null,
        notes: notes.trim() || null,
        approx_age: approx_age === "" ? null : Number(approx_age),
        borough_id: borough_id === "" ? null : Number(borough_id),
        category_ids: categoryIds,
        new_categories: newCategories,
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
    <div className="candidate-review">
      {suggestions.length > 0 && (
        <div>
          <strong>Invitados existentes con nombre parecido:</strong>
          <ul className="item-list">
            {suggestions.map((s) => (
              <li key={s.id}>
                {s.full_name}{" "}
                <button type="button" onClick={() => acceptExisting(s.id)} disabled={busy}>
                  Vincular con este
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form onSubmit={submitNew} className="form-grid" aria-label={`Crear invitado nuevo para ${candidate.extracted_name}`}>
        <h4>O crear un invitado nuevo</h4>
        <label>
          Nombre completo
          <input value={full_name} onChange={(e) => setFullName(e.target.value)} maxLength={255} />
        </label>
        <label>
          Organización
          <input value={organization} onChange={(e) => setOrganization(e.target.value)} maxLength={255} />
        </label>
        <label>
          Puesto o rol
          <input value={role} onChange={(e) => setRole(e.target.value)} maxLength={255} />
        </label>
        <label>
          Edad aproximada
          <input type="number" min="0" max="120" value={approx_age} onChange={(e) => setApproxAge(e.target.value)} />
        </label>
        <label>
          Alcaldía
          <select value={borough_id} onChange={(e) => setBoroughId(e.target.value)}>
            <option value="">— Sin alcaldía —</option>
            {boroughs.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>

        <fieldset>
          <legend>Categorías</legend>
          <div className="checks">
            {categories.map((c) => (
              <label key={c.id} className="check">
                <input type="checkbox" checked={categoryIds.includes(c.id)} onChange={() => toggleCategory(c.id)} />
                {c.name}
              </label>
            ))}
          </div>
          {newCategories.length > 0 && (
            <ul className="chips" aria-label="Categorías nuevas">
              {newCategories.map((name) => (
                <li key={name}>
                  {name}{" "}
                  <button type="button" aria-label={`Quitar ${name}`} onClick={() => setNewCategories((prev) => prev.filter((n) => n !== name))}>
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="inline-form">
            <label>
              Nueva categoría
              <input
                value={newCategoryInput}
                onChange={(e) => setNewCategoryInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addNewCategory();
                  }
                }}
                maxLength={150}
              />
            </label>
            <button type="button" onClick={addNewCategory} disabled={!newCategoryInput.trim()}>
              Agregar categoría
            </button>
          </div>
        </fieldset>

        <label>
          Notas
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button type="submit" disabled={busy}>
            Crear y aceptar
          </button>
          <button type="button" onClick={reject} className="danger" disabled={busy}>
            Rechazar candidato
          </button>
          <button type="button" onClick={onCancel} disabled={busy}>
            Cancelar
          </button>
        </div>
      </form>
    </div>
  );
}
