import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";

const LINKS = [
  { to: "/", label: "Inicio", end: true },
  { to: "/catalogs", label: "Catálogos" },
  { to: "/guests", label: "Invitados" },
  { to: "/videos", label: "Videos" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="layout">
      <header className="topbar">
        <strong className="brand">X Live Medios</strong>
        <nav aria-label="Navegación principal">
          {LINKS.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end}>
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="user-box">
          <span>{user?.username}</span>
          <button type="button" onClick={logout}>
            Salir
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
