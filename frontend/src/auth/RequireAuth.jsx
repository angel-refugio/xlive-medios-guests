import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext.jsx";

// Protege las rutas internas: sin sesión redirige al login y recuerda a dónde iba.
export default function RequireAuth({ children }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") return <p className="center-note">Cargando…</p>;
  if (status !== "auth") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}
