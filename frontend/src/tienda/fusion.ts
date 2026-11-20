import type {
  FuenteFallida,
  FuenteRegistrada,
  Recomendacion,
  RecomendacionFusionada,
  ResultadoFusion,
} from './tipos.ts';

export const TOP_K = 10;

export function normalizar(lista: Recomendacion[]): Recomendacion[] {
  const mejores = new Map<number, number>();
  for (const { producto_id, score } of lista) {
    if (!Number.isFinite(score)) continue;
    const previo = mejores.get(producto_id);
    if (previo === undefined || score > previo) mejores.set(producto_id, score);
  }
  const scores = [...mejores.values()];
  const min = Math.min(...scores);
  const rango = Math.max(...scores) - min;
  return [...mejores].map(([producto_id, score]) => ({
    producto_id,
    score: rango > 0 ? (score - min) / rango : 1,
  }));
}

export function fusionar(
  productoId: number,
  porFuente: Record<string, Recomendacion[]>,
  pesos: Record<string, number> = {},
  k: number = TOP_K,
): RecomendacionFusionada[] {
  const activas = Object.keys(porFuente).filter(id => (pesos[id] ?? 1) > 0);
  const totalPesos = activas.reduce((suma, id) => suma + (pesos[id] ?? 1), 0);
  const acumulado = new Map<number, RecomendacionFusionada>();

  for (const fuente of activas) {
    const peso = (pesos[fuente] ?? 1) / totalPesos;
    const sinX = porFuente[fuente].filter(item => item.producto_id !== productoId);
    for (const { producto_id, score } of normalizar(sinX)) {
      const item = acumulado.get(producto_id) ?? { producto_id, score: 0, aportes: {} };
      item.aportes[fuente] = score * peso;
      item.score += score * peso;
      acumulado.set(producto_id, item);
    }
  }

  return [...acumulado.values()]
    .sort((a, b) =>
      b.score - a.score
      || Object.keys(b.aportes).length - Object.keys(a.aportes).length
      || a.producto_id - b.producto_id)
    .slice(0, k);
}

export interface ResultadosPorFuente {
  porFuente: Record<string, Recomendacion[]>;
  fallidas: FuenteFallida[];
}

export async function consultarFuentes(
  productoId: number,
  fuentes: FuenteRegistrada[],
): Promise<ResultadosPorFuente> {
  const resultados = await Promise.allSettled(fuentes.map(f => f.ejecutar(productoId)));
  const porFuente: Record<string, Recomendacion[]> = {};
  const fallidas: FuenteFallida[] = [];
  resultados.forEach((resultado, i) => {
    const { id } = fuentes[i];
    if (resultado.status === 'fulfilled') porFuente[id] = resultado.value;
    else fallidas.push({
      fuente: id,
      error: resultado.reason instanceof Error ? resultado.reason.message : String(resultado.reason),
    });
  });
  return { porFuente, fallidas };
}

export function pesosPorDefecto(fuentes: FuenteRegistrada[]): Record<string, number> {
  return Object.fromEntries(fuentes.map(f => [f.id, f.peso ?? 1]));
}

// Pesos aprendidos para las fuentes registradas; las que no aparecen ahí conservan su peso.
export function pesosAprendidos(
  fuentes: FuenteRegistrada[],
  aprendidos: Record<string, number>,
): Record<string, number> {
  return Object.fromEntries(fuentes.map(f => [f.id, aprendidos[f.id] ?? f.peso ?? 1]));
}

export async function recomendar(
  productoId: number,
  fuentes: FuenteRegistrada[],
  pesos?: Record<string, number>,
  k: number = TOP_K,
): Promise<ResultadoFusion> {
  const { porFuente, fallidas } = await consultarFuentes(productoId, fuentes);
  return { recomendaciones: fusionar(productoId, porFuente, pesos ?? pesosPorDefecto(fuentes), k), fallidas };
}
