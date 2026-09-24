// Paginación compartida por las listas (invitados, videos).
export default function Pager({ page, pageSize, total, noun, onPage }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav className="pager" aria-label="Paginación">
      <button onClick={() => onPage(page - 1)} disabled={page <= 1}>
        Anterior
      </button>
      <span>{`Página ${page} de ${totalPages} · ${total} ${noun}`}</span>
      <button onClick={() => onPage(page + 1)} disabled={page >= totalPages}>
        Siguiente
      </button>
    </nav>
  );
}
