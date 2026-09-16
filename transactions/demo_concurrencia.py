import threading
import time
from transactions.lock_manager import LockManager
from transactions.transaction_manager import Transaction


def _transaccion_transferencia(tabla, locks, delta, usar_locks, resultados, nombre):
    txn = Transaction(tabla, locks, usar_locks=usar_locks)
    try:
        valor = txn.leer("X", modo="exclusivo")
        time.sleep(0.05)  # Fuerza el cruce de hilos
        txn.escribir("X", valor + delta)
        txn.commit()
        resultados.append(f"{nombre} ({txn.id}) leyo X={valor}, escribio X={valor + delta}, COMMIT")
    except Exception as e:
        txn.rollback()
        resultados.append(f"{nombre} ({txn.id}) fallo y se hizo ROLLBACK: {e}")


def correr_demo(usar_locks):
    tabla = {"X": 100}
    locks = LockManager()
    resultados = []

    hilo_t1 = threading.Thread(
        target=_transaccion_transferencia,
        args=(tabla, locks, -10, usar_locks, resultados, "T1 (X = X - 10)")
    )
    hilo_t2 = threading.Thread(
        target=_transaccion_transferencia,
        args=(tabla, locks, +100, usar_locks, resultados, "T2 (X = X + 100)")
    )

    hilo_t1.start()
    hilo_t2.start()
    hilo_t1.join()
    hilo_t2.join()

    esperado = 100 - 10 + 100
    return tabla["X"], esperado, resultados


def main():
    print("=" * 70)
    print("DEMOSTRACION DE CONCURRENCIA: problema de 'actualizacion perdida'")
    print("=" * 70)

    print("\n--- CASO 1: SIN control de concurrencia (sin locks) ---")
    for intento in range(1, 4):
        final, esperado, log = correr_demo(usar_locks=False)
        for linea in log:
            print("   ", linea)
        estado = "CORRECTO" if final == esperado else "*** RACE CONDITION: SE PERDIO UNA ACTUALIZACION ***"
        print(f"   Intento {intento}: X final = {final} (esperado {esperado}) -> {estado}\n")

    print("\n--- CASO 2: CON control de concurrencia (bloqueo exclusivo PX) ---")
    for intento in range(1, 4):
        final, esperado, log = correr_demo(usar_locks=True)
        for linea in log:
            print("   ", linea)
        estado = "CORRECTO" if final == esperado else "ERROR INESPERADO"
        print(f"   Intento {intento}: X final = {final} (esperado {esperado}) -> {estado}\n")

    print("=" * 70)
    print("Conclusion: Sin locks, el resultado de X varia por race condition.")
    print("Con LockManager, las transacciones se serializan correctamente.")
    print("=" * 70)


if __name__ == "__main__":
    main()