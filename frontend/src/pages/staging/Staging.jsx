import { NavLink, Navigate, useParams } from "react-router-dom";
import ContactCandidateQueue from "./ContactCandidateQueue.jsx";
import GuestCandidateQueue from "./GuestCandidateQueue.jsx";
import NoGuestsVideos from "./NoGuestsVideos.jsx";

// Las 3 vistas de Staging Review comparten pantalla, como los catálogos (Catalogs.jsx).
const TABS = [
  { key: "guest-candidates", label: "Invitados candidatos", Component: GuestCandidateQueue },
  { key: "contact-candidates", label: "Contactos candidatos", Component: ContactCandidateQueue },
  { key: "no-guests", label: "Videos sin invitados", Component: NoGuestsVideos },
];

export default function Staging() {
  const { tab } = useParams();
  const current = TABS.find((t) => t.key === tab);
  if (!current) return <Navigate to={`/staging/${TABS[0].key}`} replace />;

  return (
    <section>
      <h1>Staging Review</h1>
      <p className="muted">
        Todo lo que trae la ingesta automática es candidato: revísalo, edítalo si hace falta, y
        acéptalo o recházalo antes de que se convierta en dato final.
      </p>
      <nav className="tabs" aria-label="Vistas de Staging Review">
        {TABS.map((t) => (
          <NavLink key={t.key} to={`/staging/${t.key}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <current.Component key={current.key} />
    </section>
  );
}
