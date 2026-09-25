import { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, useParams } from "react-router-dom";
import { api } from "../api/client.js";

// Los 6 catálogos comparten pantalla: solo cambia la ruta de la API.
// Los programas, además, permiten asignar sus conductores (catálogo "hosts").
export const CATALOGS = [
  { key: "guest-categories", label: "Categorías de invitado" },
  { key: "boroughs", label: "Alcaldías" },
  { key: "video-types", label: "Tipos de video" },
  { key: "contact-types", label: "Tipos de contacto" },
  { key: "programs", label: "Programas" },
  { key: "hosts", label: "Conductores" },
];

export default function Catalogs() {
  const { key } = useParams();
  const catalog = CATALOGS.find((c) => c.key === key);
  if (!catalog) return <Navigate to={`/catalogs/${CATALOGS[0].key}`} replace />;

  return (
    <section>
      <h1>Catálogos</h1>
      <nav className="tabs" aria-label="Catálogos disponibles">
        {CATALOGS.map((c) => (
          <NavLink key={c.key} to={`/catalogs/${c.key}`}>
            {c.label}
          </NavLink>
        ))}
      </nav>
      {/* key: al cambiar de catálogo se reinicia todo el estado de la pantalla */}
      <CatalogManager key={catalog.key} catalog={catalog} />
    </section>
  );
}

function CatalogManager({ catalog }) {
  const path = `/${catalog.key}`;
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  const [newName, setNewName] = useState("");
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);

  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState("");
  const [rowError, setRowError] = useState("");

  // Se piden siempre todos (activos e inactivos); el filtro "mostrar desactivados" es local.
  const load = useCallback(async () => {
    try {
      setItems(await api.get(path, { include_inactive: true }));
      setLoadError("");
    } catch (err) {
      console.error(`[pages.Catalogs.load] No se pudo cargar ${path}:`, err);
      setLoadError(err.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    load();
  }, [load]);

  // Conductores de cada programa (solo en el catálogo de programas).
  const isPrograms = catalog.key === "programs";
  const [hosts, setHosts] = useState([]);
  const [links, setLinks] = useState([]);
  const [hostsEditingId, setHostsEditingId] = useState(null);
  const [selectedHostIds, setSelectedHostIds] = useState([]);

  const loadHosts = useCallback(async () => {
    if (!isPrograms) return;
    try {
      const [hostList, linkList] = await Promise.all([
        api.get("/hosts", { include_inactive: true }),
        api.get("/program-hosts"),
      ]);
      setHosts(hostList);
      setLinks(linkList);
    } catch (err) {
      console.error("[pages.Catalogs.loadHosts] No se pudieron cargar los conductores:", err);
      setRowError(err.message);
    }
  }, [isPrograms]);

  useEffect(() => {
    loadHosts();
  }, [loadHosts]);

  const hostIdsOf = (programId) => links.filter((l) => l.program_id === programId).map((l) => l.host_id);
  const hostNamesOf = (programId) =>
    hostIdsOf(programId)
      .map((hostId) => hosts.find((h) => h.id === hostId)?.name)
      .filter(Boolean)
      .join(", ");

  function startEditHosts(item) {
    setRowError("");
    setEditingId(null);
    setHostsEditingId(item.id);
    setSelectedHostIds(hostIdsOf(item.id));
  }

  function toggleHost(hostId) {
    setSelectedHostIds((current) =>
      current.includes(hostId) ? current.filter((id) => id !== hostId) : [...current, hostId]
    );
  }

  async function saveHosts(item) {
    setRowError("");
    setBusy(true);
    try {
      await api.put(`/program-hosts/${item.id}`, { host_ids: selectedHostIds });
      setHostsEditingId(null);
      await loadHosts();
    } catch (err) {
      setRowError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function onAdd(event) {
    event.preventDefault();
    setFormError("");
    setBusy(true);
    try {
      await api.post(path, { name: newName });
      setNewName("");
      await load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function startEdit(item) {
    setRowError("");
    setHostsEditingId(null);
    setEditingId(item.id);
    setEditName(item.name);
  }

  function cancelEdit() {
    setEditingId(null);
    setRowError("");
  }

  async function patchItem(item, body, onDone) {
    setRowError("");
    setBusy(true);
    try {
      await api.patch(`${path}/${item.id}`, body);
      if (onDone) onDone();
      await load();
    } catch (err) {
      setRowError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const visible = showInactive ? items : items.filter((i) => i.is_active);

  return (
    <div className="card-wide">
      <h2>{catalog.label}</h2>

      <form onSubmit={onAdd} className="inline-form">
        <label>
          Nuevo nombre
          <input value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={150} />
        </label>
        <button type="submit" disabled={busy || !newName.trim()}>
          Agregar
        </button>
      </form>
      {formError && (
        <p role="alert" className="error">
          {formError}
        </p>
      )}

      <label className="check">
        <input
          type="checkbox"
          checked={showInactive}
          onChange={(e) => setShowInactive(e.target.checked)}
        />
        Mostrar desactivados
      </label>

      {rowError && (
        <p role="alert" className="error">
          {rowError}
        </p>
      )}
      {loading && <p className="muted">Cargando…</p>}
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {!loading && !loadError && visible.length === 0 && (
        <p className="muted">No hay registros{showInactive ? "" : " activos"}.</p>
      )}

      <ul className="item-list">
        {visible.map((item) => (
          <li key={item.id} className={item.is_active ? "" : "inactive"}>
            {editingId === item.id ? (
              <form
                className="inline-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  patchItem(item, { name: editName }, () => setEditingId(null));
                }}
              >
                <input
                  aria-label={`Nuevo nombre para ${item.name}`}
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  maxLength={150}
                  autoFocus
                />
                <button type="submit" disabled={busy || !editName.trim()}>
                  Guardar
                </button>
                <button type="button" onClick={cancelEdit}>
                  Cancelar
                </button>
              </form>
            ) : isPrograms && hostsEditingId === item.id ? (
              <form
                className="inline-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  saveHosts(item);
                }}
              >
                <fieldset>
                  <legend>Conductores de {item.name}</legend>
                  {hosts
                    .filter((h) => h.is_active || selectedHostIds.includes(h.id))
                    .map((h) => (
                      <label key={h.id} className="check">
                        <input
                          type="checkbox"
                          checked={selectedHostIds.includes(h.id)}
                          onChange={() => toggleHost(h.id)}
                        />
                        {h.name}
                        {!h.is_active && <em> (desactivado)</em>}
                      </label>
                    ))}
                  {hosts.length === 0 && (
                    <p className="muted">Primero crea conductores en la pestaña «Conductores».</p>
                  )}
                </fieldset>
                <button type="submit" disabled={busy}>
                  Guardar conductores
                </button>
                <button type="button" onClick={() => setHostsEditingId(null)}>
                  Cancelar
                </button>
              </form>
            ) : (
              <>
                <span className="item-name">
                  {item.name}
                  {!item.is_active && <em> (desactivado)</em>}
                  {isPrograms && (
                    <small className="muted"> · Conductores: {hostNamesOf(item.id) || "—"}</small>
                  )}
                </span>
                <span className="item-actions">
                  {isPrograms && (
                    <button
                      type="button"
                      aria-label={`Conductores de ${item.name}`}
                      onClick={() => startEditHosts(item)}
                      disabled={busy}
                    >
                      Conductores
                    </button>
                  )}
                  <button
                    type="button"
                    aria-label={`Renombrar ${item.name}`}
                    onClick={() => startEdit(item)}
                    disabled={busy}
                  >
                    Renombrar
                  </button>
                  <button
                    type="button"
                    aria-label={`${item.is_active ? "Desactivar" : "Activar"} ${item.name}`}
                    onClick={() => patchItem(item, { is_active: !item.is_active })}
                    disabled={busy}
                  >
                    {item.is_active ? "Desactivar" : "Activar"}
                  </button>
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
