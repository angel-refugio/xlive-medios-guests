import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Pager from "../../components/Pager.jsx";
import { GUEST_STATUS_LABELS, SOURCE_LABELS, dateOnly } from "./labels.js";

export default function VideoList() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const source = params.get("source") || "";
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError("");
    api
      .get("/videos", { page, source })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        console.error("[pages.VideoList.load] No se pudo cargar la lista de videos:", err);
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [page, source]);

  const update = (next) => {
    const merged = { page: String(page), source, ...next };
    const clean = {};
    if (merged.source) clean.source = merged.source;
    if (Number(merged.page) > 1) clean.page = String(merged.page);
    setParams(clean);
  };

  return (
    <section>
      <div className="page-head">
        <h1>Videos</h1>
        <Link to="/videos/new" className="button-link">
          Nuevo video
        </Link>
      </div>

      <label className="filter">
        Origen
        <select value={source} onChange={(e) => update({ source: e.target.value, page: 1 })}>
          <option value="">Todos</option>
          <option value="manual">Manuales</option>
          <option value="youtube">YouTube</option>
        </select>
      </label>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!data && !error && <p className="muted">Cargando…</p>}
      {data && data.total === 0 && (
        <p className="muted">{source ? "No hay videos con ese origen." : "Todavía no hay videos registrados."}</p>
      )}
      {data && data.total > 0 && data.items.length === 0 && (
        <p className="muted">
          Esta página no tiene videos. <button onClick={() => update({ page: 1 })}>Ir a la primera página</button>
        </p>
      )}

      {data && data.items.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Título</th>
              <th>ID de YouTube</th>
              <th>Fecha</th>
              <th>Tipo</th>
              <th>Programa</th>
              <th>Invitados</th>
              <th>Origen</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((video) => (
              <tr key={video.id}>
                <td>
                  <Link to={`/videos/${video.id}`}>{video.title}</Link>
                </td>
                <td>{video.youtube_video_id}</td>
                <td>{dateOnly(video.published_at) || "—"}</td>
                <td>{video.video_type?.name || "—"}</td>
                <td>{video.program?.name || "—"}</td>
                <td>{GUEST_STATUS_LABELS[video.guest_status] || video.guest_status}</td>
                <td>{SOURCE_LABELS[video.source] || video.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {data && data.total > 0 && (
        <Pager
          page={page}
          pageSize={data.page_size}
          total={data.total}
          noun="videos"
          onPage={(n) => update({ page: n })}
        />
      )}
    </section>
  );
}
