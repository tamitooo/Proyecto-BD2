"""
Configuración de pytest para el proyecto.

Agrega la raíz del repositorio a `sys.path` para que las pruebas puedan
importar los paquetes del motor (`storage`, `indexes`, `operators`,
`query`, `benchmarks`) sin necesidad de instalar el proyecto como paquete
ni de exportar `PYTHONPATH`.

Con esto funcionan las tres formas habituales de ejecutar la suite:

    python -m pytest
    pytest
    python -m unittest discover -s tests -t .
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
