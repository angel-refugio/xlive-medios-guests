import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client.js";
import { useCatalog } from "../../hooks/useCatalog.js";

const SOURCE_LABELS = { manual: "captura manual", video_description: "descripción del video" };

// Contactos del invitado: agregar, editar y borrar (con confirmación).
export default function Contacts({ guestId }) {
  const base = `/guests/${guestId}/contacts`;
  const contactTypes = useCatalog("contact-types");
  const [contacts, setContacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setContacts(await api.get(base));
      setLoadError("");
    } catch (err) {
      console.error("[pages.Contacts.load] No se pudieron cargar los contactos:", err);
      setLoadError(err.message);
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    load();
  }, [load]);

  async function onDelete(contact) {
    setError("");
    if (!window.confirm(`¿Borrar el contacto "${contact.value}"? Esta acción no se puede deshacer.`)) return;
    try {
      await api.del(`${base}/${contact.id}`);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="card-wide contacts">
      <h2>Contactos</h2>
      {loading && <p className="muted">Cargando…</p>}
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!loading && !loadError && contacts.length === 0 && (
        <p className="muted">Este invitado aún no tiene contactos.</p>
      )}

      <ul className="item-list">
        {contacts.map((contact) => (
          <li key={contact.id} className="contact-row">
            {editingId === contact.id ? (
              <ContactForm
                label="Editar contacto"
                submitLabel="Guardar"
                contact={contact}
                types={contactTypes.items}
                onSubmit={async (body) => {
                  await api.patch(`${base}/${contact.id}`, body);
                  setEditingId(null);
                  await load();
                }}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <>
                <span className="item-name">
                  <strong>{contact.contact_type.name}:</strong> {contact.value}
                  {contact.note && <span className="muted"> — {contact.note}</span>}
                  <br />
                  <small className="muted">
                    {contact.verified ? "Verificado" : "Sin verificar"} ·{" "}
                    {SOURCE_LABELS[contact.source] || contact.source}
                  </small>
                </span>
                <span className="item-actions">
                  <button
                    type="button"
                    aria-label={`Editar contacto ${contact.value}`}
                    onClick={() => {
                      setError("");
                      setEditingId(contact.id);
                    }}
                  >
                    Editar
                  </button>
                  <button
                    type="button"
                    className="danger"
                    aria-label={`Borrar contacto ${contact.value}`}
                    onClick={() => onDelete(contact)}
                  >
                    Borrar
                  </button>
                </span>
              </>
            )}
          </li>
        ))}
      </ul>

      <h3>Agregar contacto</h3>
      {contactTypes.error && <p className="error">{contactTypes.error}</p>}
      {!contactTypes.loading && contactTypes.items.length === 0 && !contactTypes.error && (
        <p className="muted">
          No hay tipos de contacto. Créalos primero en Catálogos → Tipos de contacto.
        </p>
      )}
      <ContactForm
        key={contacts.length /* se reinicia al agregar uno nuevo */}
        label="Nuevo contacto"
        submitLabel="Agregar contacto"
        types={contactTypes.items}
        onSubmit={async (body) => {
          await api.post(base, body);
          await load();
        }}
      />
    </div>
  );
}

function ContactForm({ label, submitLabel, contact, types, onSubmit, onCancel }) {
  const [typeId, setTypeId] = useState(contact ? String(contact.contact_type.id) : "");
  const [value, setValue] = useState(contact?.value ?? "");
  const [note, setNote] = useState(contact?.note ?? "");
  const [verified, setVerified] = useState(contact?.verified ?? false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // Si el contacto ya tenía un tipo hoy desactivado, se conserva como opción.
  const options =
    contact && !types.some((t) => t.id === contact.contact_type.id)
      ? [...types, { ...contact.contact_type }]
      : types;

  async function submit(event) {
    event.preventDefault();
    setError("");
    if (!typeId) {
      setError("Elige el tipo de contacto");
      return;
    }
    if (!value.trim()) {
      setError("El valor del contacto es obligatorio");
      return;
    }
    setSaving(true);
    try {
      await onSubmit({
        contact_type_id: Number(typeId),
        value: value.trim(),
        note: note.trim() === "" ? null : note.trim(),
        verified,
      });
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  }

  return (
    <form aria-label={label} onSubmit={submit} className="form-grid contact-form">
      <label>
        Tipo de contacto
        <select value={typeId} onChange={(e) => setTypeId(e.target.value)}>
          <option value="">— Elige un tipo —</option>
          {options.map((t) => (
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
      <label className="check">
        <input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} />
        Verificado
      </label>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="form-actions">
        <button type="submit" disabled={saving}>
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Cancelar
          </button>
        )}
      </div>
    </form>
  );
}
