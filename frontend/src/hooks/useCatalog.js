import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client.js";

// Carga los registros ACTIVOS de un catálogo (guest-categories, boroughs, contact-types…).
// `reload` vuelve a pedirlos (p. ej. después de crear un registro desde otra pantalla).
export function useCatalog(key) {
  const [state, setState] = useState({ items: [], loading: true, error: "" });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api
      .get(`/${key}`)
      .then((items) => {
        if (!cancelled) setState({ items, loading: false, error: "" });
      })
      .catch((err) => {
        console.error(`[hooks.useCatalog] No se pudo cargar el catálogo ${key}:`, err);
        if (!cancelled) setState({ items: [], loading: false, error: err.message });
      });
    return () => {
      cancelled = true;
    };
  }, [key, version]);

  const reload = useCallback(() => setVersion((n) => n + 1), []);
  return { ...state, reload };
}
