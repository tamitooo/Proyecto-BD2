import threading
import time


class RecursoBloqueado(Exception):
    """Se lanza cuando vence el tiempo de espera por un bloqueo."""
    pass


class _Recurso:
    def __init__(self):
        self.lectores = set()
        self.escritor = None
        self.cond = threading.Condition()


class LockManager:
    """Manejador de bloqueos compartidos (PS) y exclusivos (PX)."""
    TIMEOUT_SEGUNDOS = 2.0

    def __init__(self):
        self._recursos = {}
        self._lock_tabla = threading.Lock()
        self._locks_por_txn = {}

    def _get_recurso(self, recurso_id):
        with self._lock_tabla:
            if recurso_id not in self._recursos:
                self._recursos[recurso_id] = _Recurso()
            return self._recursos[recurso_id]

    def acquire_shared(self, txn_id, recurso_id):
        """Adquiere bloqueo compartido (PS)."""
        r = self._get_recurso(recurso_id)
        inicio = time.time()
        with r.cond:
            if txn_id in r.lectores or r.escritor == txn_id:
                self._registrar(txn_id, recurso_id)
                return
            while r.escritor is not None and r.escritor != txn_id:
                restante = self.TIMEOUT_SEGUNDOS - (time.time() - inicio)
                if restante <= 0 or not r.cond.wait(timeout=restante):
                    raise RecursoBloqueado(
                        f"Timeout esperando bloqueo compartido en '{recurso_id}'"
                    )
            r.lectores.add(txn_id)
        self._registrar(txn_id, recurso_id)

    def acquire_exclusive(self, txn_id, recurso_id):
        """Adquiere bloqueo exclusivo (PX)."""
        r = self._get_recurso(recurso_id)
        inicio = time.time()
        with r.cond:
            if r.escritor == txn_id:
                return
            while True:
                otros_lectores = r.lectores - {txn_id}
                otro_escritor = r.escritor is not None and r.escritor != txn_id
                if not otros_lectores and not otro_escritor:
                    break
                restante = self.TIMEOUT_SEGUNDOS - (time.time() - inicio)
                if restante <= 0 or not r.cond.wait(timeout=restante):
                    raise RecursoBloqueado(
                        f"Timeout esperando bloqueo exclusivo en '{recurso_id}'"
                    )
            r.lectores.discard(txn_id)
            r.escritor = txn_id
        self._registrar(txn_id, recurso_id)

    def _registrar(self, txn_id, recurso_id):
        with self._lock_tabla:
            self._locks_por_txn.setdefault(txn_id, set()).add(recurso_id)

    def release_all(self, txn_id):
        """Libera todos los bloqueos tomados por la transacción (Protocolo Strict 2PL)."""
        with self._lock_tabla:
            recursos = self._locks_por_txn.pop(txn_id, set())
        for recurso_id in recursos:
            r = self._recursos.get(recurso_id)
            if not r:
                continue
            with r.cond:
                if r.escritor == txn_id:
                    r.escritor = None
                r.lectores.discard(txn_id)
                r.cond.notify_all()