export const EXTRACTION_METHOD_LABELS = { regex: "Patrón de texto", llm: "IA (Ollama)" };

export const CANDIDATE_STATUS_LABELS = { pending: "Pendiente", accepted: "Aceptado", rejected: "Rechazado" };

// Id de la relación del catálogo que coincide con la que propone la IA ("manager" ↔ "Mánager"),
// sin distinguir mayúsculas ni acentos. Vacío si no hay propuesta o no está en el catálogo.
const plain = (text) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
export const matchRelationshipId = (relationships, name) => {
  if (!name) return "";
  const found = relationships.find((r) => plain(r.name) === plain(name));
  return found ? String(found.id) : "";
};

// 0.83 -> "83%"
export const confidencePercent = (value) => `${Math.round(value * 100)}%`;
