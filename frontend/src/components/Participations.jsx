import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";

const OPTIONS_LIMIT = 200;

// Participaciones (invitado ↔ video). Se usa desde dos lados:
//  - mode="guest": en el detalle de un invitado (a qué videos fue) → se elige un video para agregar.
//  - mode="video": en el detalle de un video (qué invitados salieron) → se elige un invitado para agregar.
export default function Participations({ mode, id }) {
  const isGuestMode = mode === "guest";
  const listPath = isGuestMode ? `/guests/${id}/participations` : `/videos/${id}/participations`;
  const noun = isGuestMode ? "video" : "invitado";

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [options, setOptions] = useState({ list: [], total: 0 });
  const [selected, setSelected] = useState("");
  const [notes, setNotes] = useState("");
  const [formError, setFormError] = useState("");
  const [rowError, setRowError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editNotes, setEditNotes] = useState("");

  // Lo que se muestra de cada fila según el lado desde el que se mira.
  const target = (p) =>
    isGuestMode
      ? { key: p.video.id, label: p.video.title, to: `/videos/${p.video.id}` }
      : { key: p.guest.id, label: p.guest.full_name, to: `/guests/${p.guest.id}` };
  const itemPath = (p) => `/guests/${p.guest.id}/participations/${p.id}`;

  const load = useCallback(async () => {
    try {
      setItems(await api.get(listPath));
      setLoadError("");
    } catch (err) {
      console.error("[components.Participations.load] No se pudieron cargar las participaciones:", err);
      setLoadError(err.message);
    } finally {
      setLoading(false);
    }
  }, [listPath]);

  useEffect(() => {
    load();
  }, [load]);

  // Opciones para agregar: los primeros 200 (la búsqueda por texto llega en la Fase 4).
  useEffect(() => {
    let cancelled = false;
    api
      .get(isGuestMode ? "/videos" : "/guests", { page_size: OPTIONS_LIMIT })
      .then((page) => {
        if (cancelled) return;
        const list = page.items.map((i) => ({ id: i.id, label: isGuestMode ? i.title : i.full_name }));
        setOptions({ list, total: page.total });
      })
      .catch((err) => console.error("[components.Participations.options] No se pudo cargar la lista:", err));
    return () => {
      cancelled = true;
    };
  }, [isGuestMode]);

  const linked = new Set(items.map((p) => target(p).key));
  const available = options.list.filter((o) => !linked.has(o.id));

  async function onAdd(event) {
    event.preventDefault();
    setFormError("");
    if (!selected) {
      setFormError(`Elige un ${noun}`);
      return;
    }
    const body = {
      video_id: isGuestMode ? Number(selected) : id,
      notes: notes.trim() === "" ? null : notes.trim(),
    };
    setBusy(true);
    try {
      await api.post(`/guests/${isGuestMode ? id : selected}/participations`, body);
      setSelected("");
      setNotes("");
      await load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function onSaveNotes(p) {
    setRowError("");
    setBusy(true);
    try {
      await api.patch(itemPath(p), { notes: editNotes.trim() === "" ? null : editNotes.trim() });
      setEditingId(null);
      await load();
    } catch (err) {
      setRowError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function onRemove(p) {
    setRowError("");
    const ok = window.confirm(
      `¿Quitar a ${p.guest.full_name} del video "${p.video.title}"? No se borra el invitado ni el video. Esta acción no se puede deshacer.`
    );
    if (!ok) return;
    setBusy(true);
    try {
      await api.del(itemPath(p));
      await load();
    } catch (err) {
      setRowError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card-wide contacts">
      <h2>Participaciones</h2>
      <p className="muted">
        {isGuestMode ? "Videos en los que aparece este invitado." : "Invitados que aparecen en este video."}
      </p>
      {loading && <p className="muted">Cargando…</p>}
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {rowError && (
        <p role="alert" className="error">
          {rowError}
        </p>
      )}
      {!loading && !loadError && items.length === 0 && (
        <p className="muted">
          {isGuestMode ? "Este invitado aún no tiene participaciones." : "Este video aún no tiene invitados vinculados."}
        </p>
      )}

      <ul className="item-list">
        {items.map((p) => {
          const t = target(p);
          return (
            <li key={p.id} className="contact-row">
              {editingId === p.id ? (
                <form
                  aria-label="Editar notas"
                  className="inline-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    onSaveNotes(p);
                  }}
                >
                  <label>
                    Notas de {t.label}
                    <input value={editNotes} onChange={(e) => setEditNotes(e.target.value)} autoFocus />
                  </label>
                  <button type="submit" disabled={busy}>
                    Guardar
                  </button>
                  <button type="button" onClick={() => setEditingId(null)}>
                    Cancelar
                  </button>
                </form>
              ) : (
                <>
                  <span className="item-name">
                    <Link to={t.to}>{t.label}</Link>
                    {p.notes && <span className="muted"> — {p.notes}</span>}
                  </span>
                  <span className="item-actions">
                    <button
                      type="button"
                      aria-label={`Editar notas de ${t.label}`}
                      disabled={busy}
                      onClick={() => {
                        setRowError("");
                        setEditingId(p.id);
                        setEditNotes(p.notes ?? "");
                      }}
                    >
                      Editar notas
                    </button>
                    <button
                      type="button"
                      className="danger"
                      aria-label={`Quitar ${t.label}`}
                      disabled={busy}
                      onClick={() => onRemove(p)}
                    >
                      Quitar
                    </button>
                  </span>
                </>
              )}
            </li>
          );
        })}
      </ul>

      <h3>Agregar {isGuestMode ? "a un video" : "un invitado"}</h3>
      <form aria-label="Nueva participación" onSubmit={onAdd} className="form-grid">
        <label>
          {isGuestMode ? "Video" : "Invitado"}
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            <option value="">— Elige un {noun} —</option>
            {available.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        {options.total > options.list.length && (
          <p className="muted">
            Se muestran {options.list.length} de {options.total}; la búsqueda por texto llegará en la Fase 4.
          </p>
        )}
        <label>
          Notas
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {formError && (
          <p role="alert" className="error">
            {formError}
          </p>
        )}
        <div className="form-actions">
          <button type="submit" disabled={busy}>
            Agregar participación
          </button>
        </div>
      </form>
    </div>
  );
}
