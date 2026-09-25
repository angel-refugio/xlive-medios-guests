export const GUEST_STATUS_LABELS = {
  pending: "Pendiente de revisar",
  has_guests: "Con invitados",
  no_guests: "Sin invitados",
};

export const SOURCE_LABELS = {
  manual: "Manual",
  youtube: "YouTube",
};

// Enlace directo al video en YouTube, para revisarlo desde la app.
export const youtubeUrl = (videoId) => `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`;

// "2024-05-01T10:00:00Z" → "2024-05-01" (solo la fecha, para mostrar y para <input type="date">).
export const dateOnly = (iso) => (iso ? iso.slice(0, 10) : "");
