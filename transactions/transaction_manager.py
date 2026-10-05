import itertools
from .lock_manager import LockManager
_c=itertools.count(1)
class Transaction:
    def __init__(self,tabla,locks:LockManager,usar_locks=True):self.id=f"T{next(_c)}";self.tabla=tabla;self.locks=locks;self.usar_locks=usar_locks;self._undo={}
    def leer(self,k,modo="compartido"):
        if self.usar_locks:(self.locks.acquire_exclusive if modo=="exclusivo" else self.locks.acquire_shared)(self.id,k)
        return self.tabla[k]
    def escribir(self,k,v):
        if self.usar_locks:self.locks.acquire_exclusive(self.id,k)
        self._undo.setdefault(k,self.tabla[k]);self.tabla[k]=v
    def commit(self):self._undo.clear();self.locks.release_all(self.id) if self.usar_locks else None
    def rollback(self):
        for k,v in self._undo.items():self.tabla[k]=v
        self.locks.release_all(self.id) if self.usar_locks else None
