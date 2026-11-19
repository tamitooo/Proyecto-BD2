import type { FuenteRegistrada } from './tipos.ts';

/**
 * Fuentes que usa la ficha de producto. Para sumar una, agrégala a la lista:
 *
 *   { id: 'texto', nombre: 'Descripción similar', ejecutar: recomendarPorTexto }
 *
 * `ejecutar` cumple el contrato de tipos.ts. `peso` es opcional (por defecto 1)
 * y el usuario lo puede cambiar desde la ficha.
 */
export const FUENTES: FuenteRegistrada[] = [];
