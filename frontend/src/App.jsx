import { useEffect, useState } from "react";

// Pantalla mínima de la Fase 1: confirma la conexión frontend → API → BD.
export default function App() {
  const [estado, setEstado] = useState({ cargando: true, ok: false, detalle: "" });

  useEffect(() => {
    fetch("/api/health")
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `Error HTTP ${res.status}`);
        setEstado({ cargando: false, ok: true, detalle: JSON.stringify(data) });
      })
      .catch((err) => {
        console.error("[App.useEffect] Falló la consulta a /health:", err);
        setEstado({ cargando: false, ok: false, detalle: err.message });
      });
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>X Live Medios</h1>
      <p>
        Estado de la API:{" "}
        {estado.cargando ? "consultando…" : estado.ok ? "✅ OK" : "❌ Error"}
      </p>
      {estado.detalle && <pre>{estado.detalle}</pre>}
    </main>
  );
}
