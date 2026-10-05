import unittest
from transactions.lock_manager import LockManager, RecursoBloqueado
from transactions.transaction_manager import Transaction
from transactions.demo_concurrencia import correr_demo


class TestTransactionsModule(unittest.TestCase):
    def setUp(self):
        self.tabla = {"X": 100, "Y": 200}
        self.locks = LockManager()

    def test_lectura_y_escritura_con_commit(self):
        """Verifica BEGIN TRANSACTION, modificacion y END TRANSACTION (COMMIT)."""
        txn = Transaction(self.tabla, self.locks, usar_locks=True)
        val = txn.leer("X", modo="compartido")
        self.assertEqual(val, 100)

        txn.escribir("X", 150)
        txn.commit()

        self.assertEqual(self.tabla["X"], 150)
        self.assertFalse(txn.activa)

    def test_rollback_restaura_valor_original(self):
        """Verifica la reversion de cambios al invocar ROLLBACK."""
        txn = Transaction(self.tabla, self.locks, usar_locks=True)
        txn.escribir("X", 999)
        self.assertEqual(self.tabla["X"], 999)

        txn.rollback()
        self.assertEqual(self.tabla["X"], 100)
        self.assertFalse(txn.activa)

    def test_bloqueo_exclusivo_timeout(self):
        """Verifica que un bloqueo exclusivo impida el acceso concurrente lanzando RecursoBloqueado."""
        txn1 = Transaction(self.tabla, self.locks, usar_locks=True)
        txn2 = Transaction(self.tabla, self.locks, usar_locks=True)

        txn1.leer("X", modo="exclusivo")

        with self.assertRaises(RecursoBloqueado):
            txn2.leer("X", modo="exclusivo")

        txn1.commit()

    def test_demo_concurrencia_previene_race_condition(self):
        """Ejecuta la simulacion multihilo garantizando consistencia (X = 190)."""
        final_val, esperado, _ = correr_demo(usar_locks=True)
        self.assertEqual(final_val, esperado)
        self.assertEqual(final_val, 190)


if __name__ == "__main__":
    unittest.main()