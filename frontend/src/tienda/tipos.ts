/**
 * Contrato de las fuentes de recomendación de la tienda (Parte 5).
 *
 * Cada fuente recibe el id del producto que se está viendo (X) y devuelve
 * productos parecidos con un score donde más alto = más recomendado. Si la
 * fuente trabaja con distancias, las invierte antes de devolverlas, por
 * ejemplo con 1 / (1 + distancia). La fusión normaliza cada fuente a [0, 1],
 * así que la escala del score no importa, solo el orden.
 */
export interface Recomendacion {
  producto_id: number;
  score: number;
}

export type Fuente = (productoId: number) => Promise<Recomendacion[]>;

export interface FuenteRegistrada {
  id: string;
  nombre: string;
  ejecutar: Fuente;
  peso?: number;
}

export interface RecomendacionFusionada {
  producto_id: number;
  score: number;
  aportes: Record<string, number>;
}

export interface FuenteFallida {
  fuente: string;
  error: string;
}

export interface ResultadoFusion {
  recomendaciones: RecomendacionFusionada[];
  fallidas: FuenteFallida[];
}
