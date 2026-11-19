import { recomendarPorImagen } from './visual.ts';
import { recomendarPorTexto } from './fuenteTexto.ts';
import type { FuenteRegistrada } from './tipos.ts';

/**
 * Fuentes que usa la ficha de producto. Para sumar una, agrégala a la lista:
 *
 *   { id: 'metadatos', nombre: 'Misma categoría', ejecutar: recomendarPorMetadatos }
 *
 * `ejecutar` cumple el contrato de tipos.ts. `peso` es opcional (por defecto 1)
 * y el usuario lo puede cambiar desde la ficha.
 */
export const FUENTES: FuenteRegistrada[] = [
  {
    id: 'visual',
    nombre: 'Imagen similar',
    ejecutar: recomendarPorImagen,
    peso: 1,
  },
  {
    id: 'texto',
    nombre: 'Descripción similar',
    ejecutar: recomendarPorTexto,
    peso: 1,
  },
];
