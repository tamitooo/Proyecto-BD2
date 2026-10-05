import itertools
from transactions.lock_manager import LockManager

_contador_txn = itertools.count(1)


class Transaction:
    """Modela el ciclo de vida de transacciones (BEGIN / COMMIT / ROLLBACK)."""
    def __init__(self, tabla_compartida, lock_manager: LockManager, usar_locks=True):
        self.id = f"T{next(_contador_txn)}"
        self.tabla = tabla_compartida
        self.locks = lock_manager
        self.usar_locks = usar_locks
        self.activa = True
        self._undo_buffer = {}

    def leer(self, clave, modo="compartido"):
        if self.usar_locks:
            if modo == "exclusivo":
                self.locks.acquire_exclusive(self.id, clave)
            else:
                self.locks.acquire_shared(self.id, clave)
        return self.tabla[clave]

    def escribir(self, clave, nuevo_valor):
        if self.usar_locks:
            self.locks.acquire_exclusive(self.id, clave)

        if clave not in self._undo_buffer:
            self._undo_buffer[clave] = self.tabla[clave]

        self.tabla[clave] = nuevo_valor

    def commit(self):
        """Finaliza la transacción exitosamente (END TRANSACTION / COMMIT)."""
        self._undo_buffer.clear()
        if self.usar_locks:
            self.locks.release_all(self.id)
        self.activa = False

    def rollback(self):
        """Revierte los cambios locales si ocurre un fallo o cancelacion."""
        for clave, valor_anterior in self._undo_buffer.items():
            self.tabla[clave] = valor_anterior
        self._undo_buffer.clear()
        if self.usar_locks:
            self.locks.release_all(self.id)
        self.activa = False