import { useEffect, useState } from "react";
import { api } from "../../api/client.js";

// Tamaño de lote chico a propósito: corre rápido para una demostración (ver PHASE3_PLAN.md).
// El backend admite lotes más grandes; este botón siempre pide uno chico.
const DEMO_BATCH_SIZE = 5;

const STATUS_LABELS = { completed: "completada", failed: "falló", running: "en curso" };

// Botón "Ingesta": dispara el orquestador (reglas + LLM) sobre videos nuevos del canal.
// Corre de forma síncrona: la petición no responde hasta que termina el lote completo, así
// que no hay un progreso real que mostrar (paso 1/5, 2/5…) — solo un spinner y un cronómetro,
// para confirmar que sigue viva mientras el LLM local (sin GPU) analiza cada video.
export default function IngestionRunner({ onFinished }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!running) return undefined;
    setElapsed(0);
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [running]);

  async function run() {
    setRunning(true);
    setError("");
    setResult(null);
    try {
      const created = await api.post("/ingestion/runs", { batch_size: DEMO_BATCH_SIZE });
      setResult(created);
      // Avisa a la pantalla para que recargue la revisión: los candidatos nuevos ya están guardados.
      if (onFinished) onFinished(created);
    } catch (err) {
      console.error("[pages.staging.IngestionRunner.run] Falló la corrida de ingesta:", err);
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="card-wide">
      <div className="page-head">
        <h2>Ingesta</h2>
        <button type="button" onClick={run} disabled={running}>
          {running ? "Corriendo…" : `Correr ingesta ahora (${DEMO_BATCH_SIZE} videos)`}
        </button>
      </div>
      {running && (
        <p className="muted spinner-row">
          <span className="spinner" aria-hidden="true" />
          Analizando videos con IA local ({elapsed}s transcurridos)… puede tardar varios
          minutos; no hay una barra de progreso real porque la corrida no avisa video por video.
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {result && (
        <div role="status">
          <p>
            Corrida {STATUS_LABELS[result.status] || result.status}: {result.processed_count} procesados,{" "}
            {result.success_count} exitosos, {result.error_count} con error.
          </p>
          {result.errors.length > 0 && (
            <ul className="item-list">
              {result.errors.map((e) => (
                <li key={e.id}>
                  <strong>{e.youtube_video_id}:</strong> {e.error_message}
                </li>
              ))}
            </ul>
          )}
          {result.success_count > 0 && (
            <p className="muted">
              Revisa la lista de abajo: los invitados y contactos nuevos quedan como candidatos
              pendientes.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
