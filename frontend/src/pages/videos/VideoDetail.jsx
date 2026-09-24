import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Participations from "../../components/Participations.jsx";
import { GUEST_STATUS_LABELS, SOURCE_LABELS, dateOnly } from "./labels.js";

export default function VideoDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [video, setVideo] = useState(null);
  const [error, setError] = useState("");
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setVideo(null);
    setError("");
    api
      .get(`/videos/${id}`)
      .then((result) => {
        if (!cancelled) setVideo(result);
      })
      .catch((err) => {
        console.error("[pages.VideoDetail.load] No se pudo cargar el video:", err);
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function onDelete() {
    setDeleteError("");
    const ok = window.confirm(
      `¿Borrar el video "${video.title}"? Se eliminarán también sus participaciones (los invitados no se borran). Esta acción no se puede deshacer.`
    );
    if (!ok) return;
    try {
      await api.del(`/videos/${id}`);
      navigate("/videos");
    } catch (err) {
      setDeleteError(err.message);
    }
  }

  if (error)
    return (
      <section>
        <p role="alert" className="error">
          {error}
        </p>
        <Link to="/videos">Volver a videos</Link>
      </section>
    );
  if (!video) return <p className="muted">Cargando…</p>;

  const fields = [
    ["ID de YouTube", video.youtube_video_id],
    ["Origen", SOURCE_LABELS[video.source] || video.source],
    ["Fecha de publicación", dateOnly(video.published_at)],
    ["Tipo de video", video.video_type?.name],
    ["Programa", video.program?.name],
    ["Alcaldía del evento", video.event_borough?.name],
    ["Estado de invitados", GUEST_STATUS_LABELS[video.guest_status] || video.guest_status],
    ["Descripción", video.description],
  ];

  return (
    <section>
      <div className="page-head">
        <h1>{video.title}</h1>
        <div className="item-actions">
          <Link to={`/videos/${id}/edit`} className="button-link">
            Editar
          </Link>
          <button type="button" className="danger" onClick={onDelete}>
            Borrar video
          </button>
        </div>
      </div>
      {deleteError && (
        <p role="alert" className="error">
          {deleteError}
        </p>
      )}

      <dl className="details">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value === null || value === undefined || value === "" ? "—" : value}</dd>
          </div>
        ))}
        <div>
          <dt>Parte de otro video</dt>
          <dd>
            {video.part_of_video_id ? (
              <Link to={`/videos/${video.part_of_video_id}`}>Ver video original</Link>
            ) : (
              "—"
            )}
          </dd>
        </div>
      </dl>

      <Participations mode="video" id={video.id} />
      <p>
        <Link to="/videos">← Volver a videos</Link>
      </p>
    </section>
  );
}
