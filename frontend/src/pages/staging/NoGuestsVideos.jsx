import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Pager from "../../components/Pager.jsx";
import { dateOnly, youtubeUrl } from "../videos/labels.js";

// Videos que la ingesta marcó "sin invitados" automáticamente (regla conservadora); un humano
// puede reclasificarlos si en realidad sí tienen invitados.
export default function NoGuestsVideos() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    setData(null);
    setError("");
    return api
      .get("/videos", { page, guest_status: "no_guests" })
      .then(setData)
      .catch((err) => {
        console.error("[pages.staging.NoGuestsVideos.load] No se pudo cargar la lista:", err);
        setError(err.message);
      });
  }, [page]);

  useEffect(() => {
    load();
  }, [load]);

  async function reclassify(video) {
    setBusyId(video.id);
    setError("");
    try {
      await api.patch(`/videos/${video.id}`, { guest_status: "pending" });
      navigate(`/videos/${video.id}`);
    } catch (err) {
      setError(err.message);
      setBusyId(null);
    }
  }

  return (
    <div className="card-wide">
      <p className="muted">
        La IA los marcó "sin invitados" por reglas de texto conservadoras. Si alguno sí tiene
        invitados, reclasifícalo: vuelve a "pendiente" y te lleva al video para agregarlos.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!data && !error && <p className="muted">Cargando…</p>}
      {data && data.total === 0 && <p className="muted">No hay videos marcados "sin invitados".</p>}

      {data && data.items.length > 0 && (
        <ul className="item-list">
          {data.items.map((video) => (
            <li key={video.id} className="candidate-row">
              <div className="item-name">
                <strong>{video.title}</strong>{" "}
                <small className="muted">
                  ·{" "}
                  <a href={youtubeUrl(video.youtube_video_id)} target="_blank" rel="noopener noreferrer">
                    {video.youtube_video_id}
                  </a>{" "}
                  · {dateOnly(video.published_at) || "sin fecha"}
                </small>
              </div>
              <div className="item-actions">
                <button type="button" onClick={() => reclassify(video)} disabled={busyId === video.id}>
                  Sí tiene invitados
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {data && data.total > 0 && (
        <Pager page={page} pageSize={data.page_size} total={data.total} noun="videos" onPage={(n) => setParams(n > 1 ? { page: String(n) } : {})} />
      )}
    </div>
  );
}
