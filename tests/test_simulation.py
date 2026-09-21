import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from client import Client
from exceptions import InvalidOperationError
from simulation import BankSimulation
from transaction import TransactionStatus

Client.PBKDF2_ITERATIONS = 1_000

DAYTIME = datetime(2026, 1, 1, 12, 0)


def run_simulation(num_clients=5, num_accounts=8, num_transactions=20, seed=1):
    return BankSimulation(
        num_clients=num_clients,
        num_accounts=num_accounts,
        num_transactions=num_transactions,
        seed=seed,
        time_provider=lambda: DAYTIME,
    ).run()


class TestBankSimulationGeneration(unittest.TestCase):

    def test_generates_requested_number_of_clients_and_accounts(self):
        simulation = run_simulation(num_clients=5, num_accounts=8, num_transactions=10)
        self.assertEqual(len(simulation.clients), 5)
        self.assertEqual(len(simulation.accounts), 8)

    def test_every_client_has_an_account(self):
        simulation = run_simulation(num_clients=6, num_accounts=6)
        for client in simulation.clients:
            self.assertEqual(len(client.account_ids), 1)

    def test_all_clients_are_adults(self):
        simulation = run_simulation(num_clients=10, num_accounts=10)
        self.assertTrue(all(client.age >= 18 for client in simulation.clients))

    def test_invalid_configuration(self):
        with self.assertRaises(InvalidOperationError):
            BankSimulation(num_clients=5, num_accounts=3)

    def test_seed_makes_run_reproducible(self):
        first = run_simulation(seed=123)
        second = run_simulation(seed=123)
        self.assertEqual(first.get_transaction_statistics(), second.get_transaction_statistics())
        self.assertEqual(
            [client.full_name for client in first.clients],
            [client.full_name for client in second.clients],
        )


class TestBankSimulationTransactions(unittest.TestCase):

    def test_all_transactions_are_processed(self):
        simulation = run_simulation(num_transactions=15)
        self.assertEqual(len(simulation.transactions), 15)
        final_statuses = {TransactionStatus.COMPLETED, TransactionStatus.FAILED}
        self.assertTrue(all(t.status in final_statuses for t in simulation.transactions))

    def test_statistics_are_consistent(self):
        stats = run_simulation(num_transactions=25).get_transaction_statistics()
        self.assertEqual(stats["completed"] + stats["failed"], stats["total"])
        self.assertEqual(sum(stats["by_type"].values()), stats["total"])

    def test_client_history_only_contains_own_transactions(self):
        simulation = run_simulation(num_clients=6, num_accounts=10, num_transactions=30)
        client = simulation.clients[0]
        for transaction in simulation.get_client_transaction_history(client.client_id):
            participants = {
                simulation.bank.get_client_id_for_account(transaction.sender_account_id),
                simulation.bank.get_client_id_for_account(transaction.receiver_account_id),
            }
            self.assertIn(client.client_id, participants)


class TestBankSimulationReports(unittest.TestCase):

    def test_top_clients_are_sorted_descending(self):
        top = run_simulation(num_clients=6, num_accounts=10).get_top_clients(n=3)
        self.assertLessEqual(len(top), 3)
        totals = [total for _, total in top]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_most_active_client_has_longest_history(self):
        simulation = run_simulation(num_transactions=30)
        most_active = simulation.get_most_active_client()
        longest = max(
            len(simulation.get_client_transaction_history(c.client_id)) for c in simulation.clients
        )
        self.assertEqual(len(simulation.get_client_transaction_history(most_active.client_id)), longest)


if __name__ == "__main__":
    unittest.main()
