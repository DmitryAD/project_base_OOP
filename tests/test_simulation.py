import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulation import BankSimulation


def make_simulation(num_clients=5, num_accounts=8, num_transactions=20, seed=1):
    sim = BankSimulation(
        num_clients=num_clients, num_accounts=num_accounts,
        num_transactions=num_transactions, seed=seed,
    )
    sim.generate_clients()
    sim.generate_accounts()
    sim.run_transactions()
    return sim


class TestBankSimulationGeneration(unittest.TestCase):

    def test_generates_requested_number_of_clients_and_accounts(self):
        sim = make_simulation(num_clients=5, num_accounts=8, num_transactions=10)
        self.assertEqual(len(sim.clients), 5)
        self.assertEqual(len(sim.accounts), 8)

    def test_seed_makes_run_reproducible(self):
        sim1 = make_simulation(seed=123)
        sim2 = make_simulation(seed=123)
        self.assertEqual(sim1.get_transaction_statistics(), sim2.get_transaction_statistics())


class TestBankSimulationTransactions(unittest.TestCase):

    def test_transaction_log_has_requested_length(self):
        sim = make_simulation(num_transactions=15)
        self.assertEqual(len(sim.transaction_log), 15)

    def test_statistics_counts_are_consistent(self):
        sim = make_simulation(num_transactions=25)
        stats = sim.get_transaction_statistics()
        self.assertEqual(stats["completed"] + stats["failed"], stats["total"])
        self.assertEqual(sum(stats["by_type"].values()), stats["total"])

    def test_client_history_only_contains_own_transactions(self):
        sim = make_simulation(num_clients=6, num_accounts=10, num_transactions=30)
        client = sim.clients[0]
        history = sim.get_client_transaction_history(client.client_id)
        for t in history:
            sender_client = sim.bank.get_client_id_for_account(t.sender_account_id) if t.sender_account_id else None
            receiver_client = sim.bank.get_client_id_for_account(t.receiver_account_id) if t.receiver_account_id else None
            self.assertIn(client.client_id, (sender_client, receiver_client))


class TestBankSimulationReports(unittest.TestCase):

    def test_top_clients_returns_at_most_n_sorted_descending(self):
        sim = make_simulation(num_clients=6, num_accounts=10, num_transactions=20)
        top = sim.get_top_clients(n=3)
        self.assertLessEqual(len(top), 3)
        totals = [total for _, total in top]
        self.assertEqual(totals, sorted(totals, reverse=True))


if __name__ == "__main__":
    unittest.main()
