import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../App.jsx";
import { setToken } from "../api/client.js";
import { AuthProvider } from "../auth/AuthContext.jsx";
import { ROUTER_FUTURE } from "../routerFuture.js";

// Renderiza la app completa en una ruta, con sesión iniciada.
export function renderApp(path = "/") {
  setToken("tok");
  return render(
    <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>
  );
}
