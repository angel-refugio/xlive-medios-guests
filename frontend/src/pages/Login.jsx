import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";

export default function Login() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  const destino = location.state?.from || "/";
  if (status === "auth") return <Navigate to={destino} replace />;

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    setEnviando(true);
    try {
      await login(username.trim(), password);
      navigate(destino, { replace: true });
    } catch (err) {
      setError(err.message || "No se pudo iniciar sesión");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="login">
      <form onSubmit={onSubmit} className="card">
        <h1>X Live Medios</h1>
        <p className="muted">Inicia sesión para continuar</p>
        <label>
          Usuario
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            autoFocus
          />
        </label>
        <label>
          Contraseña
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <button type="submit" disabled={enviando}>
          {enviando ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </main>
  );
}
