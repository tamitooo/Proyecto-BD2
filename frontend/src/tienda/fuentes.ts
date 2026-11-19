import { recomendarPorTexto } from './fuenteTexto.ts';
import type { FuenteRegistrada } from './tipos.ts';

export const FUENTES: FuenteRegistrada[] = [
  {
    id: 'texto',
    nombre: 'Descripción similar',
    ejecutar: recomendarPorTexto,
    peso: 1,
  },
];