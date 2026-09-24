import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Pager from "../../components/Pager.jsx";

export default function GuestList() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError("");
    api
      .get("/guests", { page })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        console.error("[pages.GuestList.load] No se pudo cargar la lista de invitados:", err);
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [page]);

  const goTo = (n) => setParams(n <= 1 ? {} : { page: String(n) });

  return (
    <section>
      <div className="page-head">
        <h1>Invitados</h1>
        <Link to="/guests/new" className="button-link">
          Nuevo invitado
        </Link>
      </div>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!data && !error && <p className="muted">Cargando…</p>}

      {data && data.total === 0 && <p className="muted">Todavía no hay invitados registrados.</p>}
      {data && data.total > 0 && data.items.length === 0 && (
        <p className="muted">
          Esta página no tiene invitados. <button onClick={() => goTo(1)}>Ir a la primera página</button>
        </p>
      )}

      {data && data.items.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Categorías</th>
              <th>Alcaldía</th>
              <th>Edad aprox.</th>
              <th>Puesto o rol</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((guest) => (
              <tr key={guest.id}>
                <td>
                  <Link to={`/guests/${guest.id}`}>{guest.full_name}</Link>
                </td>
                <td>{guest.categories.map((c) => c.name).join(", ") || "—"}</td>
                <td>{guest.borough?.name || "—"}</td>
                <td>{guest.approx_age ?? "—"}</td>
                <td>{guest.role || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {data && data.total > 0 && (
        <Pager page={page} pageSize={data.page_size} total={data.total} noun="invitados" onPage={goTo} />
      )}
    </section>
  );
}
