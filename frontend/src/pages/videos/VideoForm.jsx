import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import { useCatalog } from "../../hooks/useCatalog.js";
import { GUEST_STATUS_LABELS, dateOnly } from "./labels.js";

const EMPTY = {
  youtube_video_id: "",
  title: "",
  description: "",
  published_date: "",
  video_type_id: "",
  program_id: "",
  event_borough_id: "",
  part_of_video_id: "",
  guest_status: "pending",
};

const orNull = (text) => (text.trim() === "" ? null : text.trim());
const numOrNull = (value) => (value === "" ? null : Number(value));

// Añade el registro que el video ya tenía si hoy está desactivado (para no perderlo al editar).
const withCurrent = (items, current) =>
  current && !items.some((i) => i.id === current.id) ? [...items, current] : items;

// Crear (/videos/new) y editar (/videos/:id/edit). Obligatorios: ID de YouTube y título.
export default function VideoForm() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const videoTypes = useCatalog("video-types");
  const programs = useCatalog("programs");
  const boroughs = useCatalog("boroughs");

  const [form, setForm] = useState(EMPTY);
  const [original, setOriginal] = useState(null); // video cargado al editar
  const [videoOptions, setVideoOptions] = useState([]); // para "parte de otro video"
  const [loading, setLoading] = useState(isEdit);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isEdit) return;
    let cancelled = false;
    api
      .get(`/videos/${id}`)
      .then((video) => {
        if (cancelled) return;
        setOriginal(video);
        setForm({
          youtube_video_id: video.youtube_video_id,
          title: video.title,
          description: video.description ?? "",
          published_date: dateOnly(video.published_at),
          video_type_id: video.video_type ? String(video.video_type.id) : "",
          program_id: video.program ? String(video.program.id) : "",
          event_borough_id: video.event_borough ? String(video.event_borough.id) : "",
          part_of_video_id: video.part_of_video_id ? String(video.part_of_video_id) : "",
          guest_status: video.guest_status,
        });
        setLoading(false);
      })
      .catch((err) => {
        console.error("[pages.VideoForm.load] No se pudo cargar el video:", err);
        if (!cancelled) {
          setLoadError(err.message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id, isEdit]);

  // Opciones para "parte de otro video" (los primeros 200; la búsqueda llega en la Fase 4).
  useEffect(() => {
    let cancelled = false;
    api
      .get("/videos", { page_size: 200 })
      .then((page) => {
        if (!cancelled) setVideoOptions(page.items);
      })
      .catch((err) => console.error("[pages.VideoForm.videoOptions] No se pudo cargar la lista:", err));
    return () => {
      cancelled = true;
    };
  }, []);

  const setField = (name) => (e) => setForm((prev) => ({ ...prev, [name]: e.target.value }));

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    if (!form.youtube_video_id.trim()) {
      setError("El ID de YouTube es obligatorio");
      return;
    }
    if (!form.title.trim()) {
      setError("El título es obligatorio");
      return;
    }
    const payload = {
      youtube_video_id: form.youtube_video_id.trim(),
      title: form.title.trim(),
      description: orNull(form.description),
      published_at: form.published_date ? `${form.published_date}T00:00:00Z` : null,
      video_type_id: numOrNull(form.video_type_id),
      program_id: numOrNull(form.program_id),
      event_borough_id: numOrNull(form.event_borough_id),
      part_of_video_id: numOrNull(form.part_of_video_id),
      guest_status: form.guest_status,
    };
    if (isEdit) {
      // La fecha solo tiene día: si no se tocó, no se envía para no borrar la hora que ya tenía.
      if (form.published_date === dateOnly(original.published_at)) delete payload.published_at;
      // Los videos de YouTube conservan su ID.
      if (original.source === "youtube") delete payload.youtube_video_id;
    }
    setSaving(true);
    try {
      const saved = isEdit ? await api.patch(`/videos/${id}`, payload) : await api.post("/videos", payload);
      navigate(`/videos/${saved.id}`);
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

  const partOfOptions = videoOptions.filter((v) => String(v.id) !== String(id));
  const currentPartOf = form.part_of_video_id;
  const partOfMissing = currentPartOf && !partOfOptions.some((v) => String(v.id) === currentPartOf);

  return (
    <section>
      <h1>{isEdit ? "Editar video" : "Nuevo video"}</h1>
      {!isEdit && (
        <p className="muted">
          Los videos cargados aquí quedan marcados como «Manual»; los que traiga la ingesta serán de «YouTube».
        </p>
      )}
      <form onSubmit={onSubmit} className="card-wide form-grid">
        <label>
          ID de YouTube
          <input
            value={form.youtube_video_id}
            onChange={setField("youtube_video_id")}
            maxLength={32}
            disabled={original?.source === "youtube"}
            required
          />
        </label>
        <label>
          Título
          <input value={form.title} onChange={setField("title")} maxLength={500} required />
        </label>
        <label>
          Descripción
          <textarea rows={3} value={form.description} onChange={setField("description")} />
        </label>
        <label>
          Fecha de publicación
          <input type="date" value={form.published_date} onChange={setField("published_date")} />
        </label>
        <label>
          Tipo de video
          <select value={form.video_type_id} onChange={setField("video_type_id")}>
            <option value="">— Sin tipo —</option>
            {withCurrent(videoTypes.items, original?.video_type).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Programa
          <select value={form.program_id} onChange={setField("program_id")}>
            <option value="">— Sin programa —</option>
            {withCurrent(programs.items, original?.program).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Alcaldía del evento
          <select value={form.event_borough_id} onChange={setField("event_borough_id")}>
            <option value="">— Sin alcaldía —</option>
            {withCurrent(boroughs.items, original?.event_borough).map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Parte de otro video
          <select value={form.part_of_video_id} onChange={setField("part_of_video_id")}>
            <option value="">— Ninguno —</option>
            {partOfMissing && <option value={currentPartOf}>Video #{currentPartOf}</option>}
            {partOfOptions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          Estado de invitados
          <select value={form.guest_status} onChange={setField("guest_status")}>
            {Object.entries(GUEST_STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
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
        <div className="form-actions">
          <button type="submit" disabled={saving}>
            {saving ? "Guardando…" : "Guardar"}
          </button>
          <Link to={isEdit ? `/videos/${id}` : "/videos"}>Cancelar</Link>
        </div>
      </form>
    </section>
  );
}
