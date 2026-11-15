import itertools
from .lock_manager import LockManager

_c = itertools.count(1)


class TransaccionTerminada(RuntimeError):
    pass


class Transaction:
    def __init__(self, tabla, locks: LockManager, usar_locks=True):
        self.id = f"T{next(_c)}"
        self.tabla = tabla
        self.locks = locks
        self.usar_locks = usar_locks
        self._undo = {}
        self.activa = True

    def _check(self):
        if not self.activa:
            raise TransaccionTerminada(f"la transacción {self.id} ya terminó")

    def leer(self, k, modo="compartido"):
        self._check()
        if self.usar_locks:
            (self.locks.acquire_exclusive if modo == "exclusivo" else self.locks.acquire_shared)(self.id, k)
        return self.tabla[k]

    def escribir(self, k, v):
        self._check()
        if self.usar_locks:
            self.locks.acquire_exclusive(self.id, k)
        self._undo.setdefault(k, self.tabla[k])
        self.tabla[k] = v

    def _end(self):
        self._undo.clear()
        if self.usar_locks:
            self.locks.release_all(self.id)
        self.activa = False

    def commit(self):
        self._check()
        self._end()

    def rollback(self):
        self._check()
        for k, v in self._undo.items():
            self.tabla[k] = v
        self._end()
