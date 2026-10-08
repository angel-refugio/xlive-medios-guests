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

// Mismo nombre sin importar mayúsculas, acentos ni signos ("Héctor A." ~ "hector a").
export const sameName = (a, b) => {
  const key = (text) => plain(text).replace(/[^a-z0-9]/g, "");
  return key(a) !== "" && key(a) === key(b);
};

// Pistas que no son una red o servicio concreto: para ellas no se ofrece "Crear tipo".
const GENERIC_TYPE_HINTS = ["handle", "url", "email", "telefono", "contacto", "otro"];
export const canCreateTypeFrom = (hint) => Boolean(hint) && !GENERIC_TYPE_HINTS.includes(plain(hint));

// "whatsapp" -> "Whatsapp" (nombre propuesto para un tipo de contacto nuevo)
export const typeNameFromHint = (hint) => {
  const text = hint.trim();
  return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase();
};

// 0.83 -> "83%"
export const confidencePercent = (value) => `${Math.round(value * 100)}%`;
