import { Navigate, Route, Routes } from "react-router-dom";
import RequireAuth from "./auth/RequireAuth.jsx";
import Layout from "./components/Layout.jsx";
import Catalogs from "./pages/Catalogs.jsx";
import Home from "./pages/Home.jsx";
import Login from "./pages/Login.jsx";
import GuestDetail from "./pages/guests/GuestDetail.jsx";
import GuestForm from "./pages/guests/GuestForm.jsx";
import GuestList from "./pages/guests/GuestList.jsx";
import VideoDetail from "./pages/videos/VideoDetail.jsx";
import VideoForm from "./pages/videos/VideoForm.jsx";
import VideoList from "./pages/videos/VideoList.jsx";

// El Router y el AuthProvider viven en main.jsx (y en las pruebas) para poder simular rutas.
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Home />} />
        <Route path="catalogs/:key?" element={<Catalogs />} />
        <Route path="guests" element={<GuestList />} />
        <Route path="guests/new" element={<GuestForm />} />
        <Route path="guests/:id" element={<GuestDetail />} />
        <Route path="guests/:id/edit" element={<GuestForm />} />
        <Route path="videos" element={<VideoList />} />
        <Route path="videos/new" element={<VideoForm />} />
        <Route path="videos/:id" element={<VideoDetail />} />
        <Route path="videos/:id/edit" element={<VideoForm />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
