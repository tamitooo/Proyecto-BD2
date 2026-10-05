import threading,time
class RecursoBloqueado(Exception):pass
class _Recurso:
    def __init__(self):self.lectores=set();self.escritor=None;self.cond=threading.Condition()
class LockManager:
    TIMEOUT_SEGUNDOS=2.0
    def __init__(self):self._recursos={};self._lock=threading.Lock();self._por_txn={}
    def _r(self,rid):
        with self._lock:return self._recursos.setdefault(rid,_Recurso())
    def _reg(self,t,r):
        with self._lock:self._por_txn.setdefault(t,set()).add(r)
    def acquire_shared(self,t,rid):
        r=self._r(rid);start=time.time()
        with r.cond:
            while r.escritor is not None and r.escritor!=t:
                rem=self.TIMEOUT_SEGUNDOS-(time.time()-start)
                if rem<=0 or not r.cond.wait(rem):raise RecursoBloqueado(f"Timeout esperando PS en '{rid}'")
            r.lectores.add(t)
        self._reg(t,rid)
    def acquire_exclusive(self,t,rid):
        r=self._r(rid);start=time.time()
        with r.cond:
            while (r.escritor not in {None,t}) or (r.lectores-{t}):
                rem=self.TIMEOUT_SEGUNDOS-(time.time()-start)
                if rem<=0 or not r.cond.wait(rem):raise RecursoBloqueado(f"Timeout esperando PX en '{rid}'")
            r.lectores.discard(t);r.escritor=t
        self._reg(t,rid)
    def release_all(self,t):
        with self._lock:resources=self._por_txn.pop(t,set())
        for rid in resources:
            r=self._recursos.get(rid)
            if r:
                with r.cond:
                    if r.escritor==t:r.escritor=None
                    r.lectores.discard(t);r.cond.notify_all()
