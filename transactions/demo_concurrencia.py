"""Demo reproducible de race condition sobre una tabla física del minigestor.

Dos hilos actualizan la MISMA fila de un HeapFile. Primero se ejecutan sin
bloqueos para producir Lost Update y luego con PX/Strict-2PL mediante
LockManager. Esto satisface el requisito de demostrar el problema y su control
sobre la misma tabla, no sobre una variable escalar aislada.
"""
from __future__ import annotations

import tempfile
import threading
import time

from storage.heap_file import HeapFile
from storage.record import Schema
from transactions.lock_manager import LockManager

_SCHEMA = Schema([("id", "INT"), ("saldo", "INT")], "id")


def _worker(heap, rid, locks, txn_id, delta, use_locks, barrier, log):
    resource = "cuentas:1"
    try:
        if use_locks:
            locks.acquire_exclusive(txn_id, resource)
        row = dict(heap.read(rid))
        original = row["saldo"]
        # Los dos hilos ya han leído antes de escribir en el caso sin locks.
        if not use_locks:
            barrier.wait(timeout=2)
        time.sleep(0.02)
        row["saldo"] = original + delta
        heap.update(rid, row)
        log.append((txn_id, original, row["saldo"], "COMMIT"))
    finally:
        if use_locks:
            locks.release_all(txn_id)


def correr_demo(usar_locks: bool):
    with tempfile.TemporaryDirectory(prefix="bd2-concurrency-") as td:
        heap = HeapFile(f"{td}/cuentas.dat", _SCHEMA)
        rid = heap.insert({"id": 1, "saldo": 100})
        locks = LockManager()
        barrier = threading.Barrier(2)
        log = []
        threads = [
            threading.Thread(target=_worker, args=(heap, rid, locks, "T1", -10, usar_locks, barrier, log)),
            threading.Thread(target=_worker, args=(heap, rid, locks, "T2", +100, usar_locks, barrier, log)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        final = heap.read(rid)["saldo"]
        esperado = 190
        return final, esperado, sorted(log)


def main():
    print("=" * 72)
    print("CONCURRENCIA SOBRE HeapFile: Lost Update y control con PX / Strict 2PL")
    print("=" * 72)
    final, esperado, log = correr_demo(False)
    print("\nSIN LOCKS")
    for item in log:
        print(" ", item)
    print(f"saldo final={final}, esperado serial={esperado}")
    print("RACE CONDITION / LOST UPDATE" if final != esperado else "resultado serial (no se reprodujo)")

    final, esperado, log = correr_demo(True)
    print("\nCON LOCK EXCLUSIVO PX")
    for item in log:
        print(" ", item)
    print(f"saldo final={final}, esperado serial={esperado}")
    print("CORRECTO" if final == esperado else "ERROR")


if __name__ == "__main__":
    main()
