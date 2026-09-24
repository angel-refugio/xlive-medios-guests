import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import Participations from "../../components/Participations.jsx";
import Contacts from "./Contacts.jsx";

export default function GuestDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [guest, setGuest] = useState(null);
  const [error, setError] = useState("");
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setGuest(null);
    setError("");
    api
      .get(`/guests/${id}`)
      .then((result) => {
        if (!cancelled) setGuest(result);
      })
      .catch((err) => {
        console.error("[pages.GuestDetail.load] No se pudo cargar el invitado:", err);
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function onDelete() {
    setDeleteError("");
    const ok = window.confirm(
      `¿Borrar a ${guest.full_name}? Se eliminarán también sus contactos y participaciones. Esta acción no se puede deshacer.`
    );
    if (!ok) return;
    try {
      await api.del(`/guests/${id}`);
      navigate("/guests");
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
        <Link to="/guests">Volver a invitados</Link>
      </section>
    );
  if (!guest) return <p className="muted">Cargando…</p>;

  const fields = [
    ["Organización", guest.organization],
    ["Puesto o rol", guest.role],
    ["Edad aproximada", guest.approx_age],
    ["Alcaldía", guest.borough?.name],
    ["Categorías", guest.categories.map((c) => c.name).join(", ")],
    ["Notas", guest.notes],
  ];

  return (
    <section>
      <div className="page-head">
        <h1>{guest.full_name}</h1>
        <div className="item-actions">
          <Link to={`/guests/${id}/edit`} className="button-link">
            Editar
          </Link>
          <button type="button" className="danger" onClick={onDelete}>
            Borrar invitado
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
      </dl>

      <Contacts guestId={guest.id} />
      <Participations mode="guest" id={guest.id} />
      <p>
        <Link to="/guests">← Volver a invitados</Link>
      </p>
    </section>
  );
}
