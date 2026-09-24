import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import { useCatalog } from "../../hooks/useCatalog.js";

const EMPTY = { full_name: "", organization: "", role: "", approx_age: "", borough_id: "", notes: "" };

const orNull = (text) => (text.trim() === "" ? null : text.trim());

// Crear (/guests/new) y editar (/guests/:id/edit) comparten formulario.
// Solo el nombre es obligatorio; un campo vacío se envía como null (borra el dato al editar).
export default function GuestForm() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const boroughs = useCatalog("boroughs");
  const categories = useCatalog("guest-categories");

  const [form, setForm] = useState(EMPTY);
  const [categoryIds, setCategoryIds] = useState([]);
  const [assigned, setAssigned] = useState([]); // categorías que ya tenía el invitado (pueden estar desactivadas)
  const [newCategories, setNewCategories] = useState([]);
  const [newCategoryInput, setNewCategoryInput] = useState("");
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isEdit) return;
    let cancelled = false;
    api
      .get(`/guests/${id}`)
      .then((guest) => {
        if (cancelled) return;
        setForm({
          full_name: guest.full_name,
          organization: guest.organization ?? "",
          role: guest.role ?? "",
          approx_age: guest.approx_age ?? "",
          borough_id: guest.borough ? String(guest.borough.id) : "",
          notes: guest.notes ?? "",
        });
        setCategoryIds(guest.categories.map((c) => c.id));
        setAssigned(guest.categories);
        setLoading(false);
      })
      .catch((err) => {
        console.error("[pages.GuestForm.load] No se pudo cargar el invitado:", err);
        if (!cancelled) {
          setLoadError(err.message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id, isEdit]);

  const setField = (name) => (e) => setForm((prev) => ({ ...prev, [name]: e.target.value }));

  // Opciones de categoría: las activas + las que el invitado ya tenía y hoy están desactivadas.
  const categoryOptions = [
    ...categories.items,
    ...assigned.filter((a) => !categories.items.some((c) => c.id === a.id)),
  ];

  function toggleCategory(catId) {
    setCategoryIds((prev) => (prev.includes(catId) ? prev.filter((x) => x !== catId) : [...prev, catId]));
  }

  function addNewCategory() {
    const name = newCategoryInput.trim().replace(/\s+/g, " ");
    if (!name) return;
    if (!newCategories.some((n) => n.toLowerCase() === name.toLowerCase())) {
      setNewCategories((prev) => [...prev, name]);
    }
    setNewCategoryInput("");
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    if (!form.full_name.trim()) {
      setError("El nombre es obligatorio");
      return;
    }
    const payload = {
      full_name: form.full_name.trim(),
      organization: orNull(form.organization),
      role: orNull(form.role),
      notes: orNull(form.notes),
      approx_age: form.approx_age === "" ? null : Number(form.approx_age),
      borough_id: form.borough_id === "" ? null : Number(form.borough_id),
      category_ids: categoryIds,
      new_categories: newCategories,
    };
    setSaving(true);
    try {
      const saved = isEdit ? await api.patch(`/guests/${id}`, payload) : await api.post("/guests", payload);
      navigate(`/guests/${saved.id}`);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  }

  if (loading) return <p className="muted">Cargando…</p>;
  if (loadError)
    return (
      <p role="alert" className="error">
        {loadError}
      </p>
    );

  return (
    <section>
      <h1>{isEdit ? "Editar invitado" : "Nuevo invitado"}</h1>
      <form onSubmit={onSubmit} className="card-wide form-grid">
        <label>
          Nombre completo
          <input value={form.full_name} onChange={setField("full_name")} maxLength={255} required />
        </label>
        <label>
          Organización
          <input value={form.organization} onChange={setField("organization")} maxLength={255} />
        </label>
        <label>
          Puesto o rol
          <input value={form.role} onChange={setField("role")} maxLength={255} />
        </label>
        <label>
          Edad aproximada
          <input type="number" min="0" max="120" value={form.approx_age} onChange={setField("approx_age")} />
        </label>
        <label>
          Alcaldía
          <select value={form.borough_id} onChange={setField("borough_id")}>
            <option value="">— Sin alcaldía —</option>
            {boroughs.items.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>

        <fieldset>
          <legend>Categorías</legend>
          {categories.error && <p className="error">{categories.error}</p>}
          {categoryOptions.length === 0 && !categories.loading && (
            <p className="muted">Aún no hay categorías; agrega una nueva abajo.</p>
          )}
          <div className="checks">
            {categoryOptions.map((c) => (
              <label key={c.id} className="check">
                <input
                  type="checkbox"
                  checked={categoryIds.includes(c.id)}
                  onChange={() => toggleCategory(c.id)}
                />
                {c.name}
                {c.is_active === false && <em> (desactivada)</em>}
              </label>
            ))}
          </div>
          {newCategories.length > 0 && (
            <ul className="chips" aria-label="Categorías nuevas">
              {newCategories.map((name) => (
                <li key={name}>
                  {name}{" "}
                  <button
                    type="button"
                    aria-label={`Quitar ${name}`}
                    onClick={() => setNewCategories((prev) => prev.filter((n) => n !== name))}
                  >
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
          <textarea rows={3} value={form.notes} onChange={setField("notes")} />
        </label>

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button type="submit" disabled={saving}>
            {saving ? "Guardando…" : "Guardar"}
          </button>
          <Link to={isEdit ? `/guests/${id}` : "/guests"}>Cancelar</Link>
        </div>
      </form>
    </section>
  );
}
