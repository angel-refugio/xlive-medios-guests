export const EXTRACTION_METHOD_LABELS = { regex: "Patrón de texto", llm: "IA (Ollama)" };

export const CANDIDATE_STATUS_LABELS = { pending: "Pendiente", accepted: "Aceptado", rejected: "Rechazado" };

// 0.83 -> "83%"
export const confidencePercent = (value) => `${Math.round(value * 100)}%`;
