import { useEffect, useState } from "react";
import { api } from "../api/client.js";

// Inicio: conserva la comprobación de la Fase 1 (frontend → API → BD).
export default function Home() {
  const [estado, setEstado] = useState({ cargando: true, ok: false, detalle: "" });

  useEffect(() => {
    api
      .get("/health")
      .then((data) => setEstado({ cargando: false, ok: true, detalle: JSON.stringify(data) }))
      .catch((err) => setEstado({ cargando: false, ok: false, detalle: err.message }));
  }, []);

  return (
    <section>
      <h1>Inicio</h1>
      <p>
        Estado de la API:{" "}
        {estado.cargando ? "consultando…" : estado.ok ? "✅ OK" : "❌ Error"}
      </p>
      {estado.detalle && <pre>{estado.detalle}</pre>}
    </section>
  );
}
