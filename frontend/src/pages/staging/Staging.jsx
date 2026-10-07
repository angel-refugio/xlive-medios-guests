import { useState } from "react";
import { NavLink, Navigate, useParams } from "react-router-dom";
import ContactCandidateQueue from "./ContactCandidateQueue.jsx";
import IngestionRunner from "./IngestionRunner.jsx";
import ReviewByVideo from "./ReviewByVideo.jsx";

// Las vistas de Staging Review comparten pantalla, como los catálogos (Catalogs.jsx). La
// revisión por video reúne invitados, "sin invitados", "sin candidatos" y posibles duplicados.
const TABS = [
  { key: "review", label: "Revisión por video", Component: ReviewByVideo },
  { key: "contact-candidates", label: "Contactos candidatos", Component: ContactCandidateQueue },
];

export default function Staging() {
  const { tab } = useParams();
  // Se incrementa al terminar una ingesta para volver a montar la vista y que cargue lo nuevo.
  const [refreshKey, setRefreshKey] = useState(0);
  const current = TABS.find((t) => t.key === tab);
  if (!current) return <Navigate to={`/staging/${TABS[0].key}`} replace />;

  return (
    <section>
      <h1>Staging Review</h1>
      <p className="muted">
        Todo lo que trae la ingesta automática es candidato: revísalo, edítalo si hace falta, y
        acéptalo o recházalo antes de que se convierta en dato final.
      </p>
      <IngestionRunner onFinished={() => setRefreshKey((n) => n + 1)} />
      <nav className="tabs" aria-label="Vistas de Staging Review">
        {TABS.map((t) => (
          <NavLink key={t.key} to={`/staging/${t.key}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <current.Component key={`${current.key}-${refreshKey}`} />
    </section>
  );
}
