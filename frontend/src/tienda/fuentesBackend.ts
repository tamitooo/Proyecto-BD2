import { fetchRecommendations } from '../api';
import type { Recomendacion } from './tipos.ts';

// Fuentes calculadas en el backend (recommender/, Persona 4).
async function desdeBackend(fuente: 'copurchase' | 'metadata', productoId: number): Promise<Recomendacion[]> {
  const { recomendaciones } = await fetchRecommendations(fuente, productoId);
  return recomendaciones.map(r => ({ producto_id: r.producto_id, score: r.score }));
}

export const recomendarPorCoCompra = (productoId: number) => desdeBackend('copurchase', productoId);
export const recomendarPorMetadatos = (productoId: number) => desdeBackend('metadata', productoId);
