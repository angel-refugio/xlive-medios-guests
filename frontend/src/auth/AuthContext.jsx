import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, clearToken, getToken, login as apiLogin, setUnauthorizedHandler } from "../api/client.js";

const AuthContext = createContext(null);

// status: "loading" (validando token guardado) | "anon" | "auth"
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState(getToken() ? "loading" : "anon");

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    setStatus("anon");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  // Si hay un token guardado, se valida con /auth/me antes de mostrar la app.
  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    api
      .get("/auth/me")
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setStatus("auth");
      })
      .catch((err) => {
        console.error("[auth.AuthProvider] Sesión guardada no válida:", err);
        if (!cancelled) logout();
      });
    return () => {
      cancelled = true;
    };
  }, [logout]);

  const login = useCallback(async (username, password) => {
    await apiLogin(username, password);
    const me = await api.get("/auth/me");
    setUser(me);
    setStatus("auth");
  }, []);

  const value = useMemo(() => ({ user, status, login, logout }), [user, status, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("[auth.useAuth] Debe usarse dentro de <AuthProvider>");
  return ctx;
}
