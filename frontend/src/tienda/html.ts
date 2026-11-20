const ENTIDADES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escaparHtml(texto: unknown): string {
  return String(texto ?? '').replace(/[&<>"']/g, (c) => ENTIDADES[c]);
}
