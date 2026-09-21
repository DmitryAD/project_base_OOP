
import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from audit import AuditSeverity
from bank import Bank
from client import Client, ClientStatus
from exceptions import (
    AccountNotFoundError,
    AuthenticationError,
    ClientBlockedError,
    ClientNotFoundError,
    InvalidOperationError,
    NightOperationRestrictedError,
)
from main import AccountStatus, PremiumAccount

Client.PBKDF2_ITERATIONS = 1_000

DAYTIME = datetime(2026, 1, 1, 12, 0)
NIGHT = datetime(2026, 1, 1, 2, 0)


def make_bank(now=DAYTIME, name="TestBank"):
    """Банк с фиксированным временем, чтобы результат не зависел от часа запуска тестов."""
    return Bank(name=name, time_provider=lambda: now)


def make_client(bank, name="Тест Тестов", password="pass"):
    return bank.add_client(Client(full_name=name, birth_date=date(1990, 1, 1), password=password))


def open_funded_account(bank, client, amount=0, **account_options):
    account = bank.open_account(client.client_id, **account_options)
    if amount:
        bank.deposit_to_account(account.account_id, amount)
    return account


class TestBankClientsAndAccounts(unittest.TestCase):

    def setUp(self):
        self.bank = make_bank()
        self.client = make_client(self.bank)

    def test_duplicate_client_is_rejected(self):
        with self.assertRaises(InvalidOperationError):
            self.bank.add_client(self.client)

    def test_unknown_client_and_account(self):
        with self.assertRaises(ClientNotFoundError):
            self.bank.get_client("missing")
        with self.assertRaises(AccountNotFoundError):
            self.bank.get_account("missing")

    def test_open_account_links_it_to_client(self):
        account = self.bank.open_account(self.client.client_id, currency="USD")
        self.assertIn(account.account_id, self.client.account_ids)
        self.assertEqual(self.bank.get_client_id_for_account(account.account_id), self.client.client_id)
        self.assertEqual(self.bank.get_client_accounts(self.client.client_id), [account])

    def test_open_account_of_given_type_with_options(self):
        account = self.bank.open_account(
            self.client.client_id, account_type="premium", overdraft_limit=300,
        )
        self.assertIsInstance(account, PremiumAccount)
        self.assertEqual(account.overdraft_limit, 300)

    def test_unknown_account_type(self):
        with self.assertRaises(InvalidOperationError):
            self.bank.open_account(self.client.client_id, account_type="crypto")

    def test_freeze_unfreeze_and_close(self):
        account = self.bank.open_account(self.client.client_id)
        self.bank.freeze_account(account.account_id)
        self.assertEqual(account.status, AccountStatus.FROZEN)
        self.bank.unfreeze_account(account.account_id)
        self.assertEqual(account.status, AccountStatus.ACTIVE)
        self.bank.close_account(account.account_id)
        self.assertEqual(account.status, AccountStatus.CLOSED)

    def test_search_accounts(self):
        make_client(self.bank, name="Борис Николаев")
        self.bank.open_account(self.client.client_id, account_type="savings", currency="RUB")
        self.bank.open_account(self.client.client_id, currency="USD")
        self.assertEqual(len(self.bank.search_accounts(owner_name="тест")), 2)
        self.assertEqual(len(self.bank.search_accounts(currency="USD")), 1)
        self.assertEqual(len(self.bank.search_accounts(account_type="SavingsAccount")), 1)


class TestBankOperations(unittest.TestCase):

    def test_withdraw_from_foreign_account_is_rejected(self):
        bank = make_bank()
        owner = make_client(bank, "Владелец")
        stranger = make_client(bank, "Посторонний")
        account = open_funded_account(bank, owner, 1000)
        with self.assertRaises(InvalidOperationError):
            bank.withdraw_from_account(account.account_id, stranger.client_id, 100)
        self.assertEqual(account.balance, 1000)

    def test_night_operations_are_forbidden(self):
        bank = make_bank(now=NIGHT)
        client = make_client(bank)
        account = bank.open_account(client.client_id)
        with self.assertRaises(NightOperationRestrictedError):
            bank.deposit_to_account(account.account_id, 100)

    def test_total_balance_by_currency(self):
        bank = make_bank()
        client = make_client(bank)
        open_funded_account(bank, client, 100, currency="RUB")
        open_funded_account(bank, client, 200, currency="RUB")
        open_funded_account(bank, client, 50, currency="USD")
        self.assertEqual(bank.get_total_balance(), {"RUB": 300, "USD": 50})

    def test_clients_ranking_is_sorted_by_balance(self):
        bank = make_bank()
        poor = make_client(bank, "Бедный")
        rich = make_client(bank, "Богатый")
        open_funded_account(bank, poor, 100)
        open_funded_account(bank, rich, 5000)
        open_funded_account(bank, rich, 900, currency="USD")
        ranking = bank.get_clients_ranking("RUB")
        self.assertEqual([client for client, _ in ranking], [rich, poor])
        self.assertEqual(ranking[0][1], 5000)


class TestBankAuthentication(unittest.TestCase):

    def setUp(self):
        self.bank = make_bank()
        self.client = make_client(self.bank, password="correct")

    def test_successful_login(self):
        self.assertTrue(self.bank.authenticate_client(self.client.client_id, "correct"))

    def test_wrong_password(self):
        with self.assertRaises(AuthenticationError):
            self.bank.authenticate_client(self.client.client_id, "wrong")

    def test_three_failures_block_client(self):
        for _ in range(2):
            with self.assertRaises(AuthenticationError):
                self.bank.authenticate_client(self.client.client_id, "wrong")
        with self.assertRaises(ClientBlockedError):
            self.bank.authenticate_client(self.client.client_id, "wrong")
        self.assertEqual(self.client.status, ClientStatus.BLOCKED)
        with self.assertRaises(ClientBlockedError):
            self.bank.authenticate_client(self.client.client_id, "correct")

    def test_successful_login_resets_counter(self):
        for _ in range(2):
            with self.assertRaises(AuthenticationError):
                self.bank.authenticate_client(self.client.client_id, "wrong")
        self.bank.authenticate_client(self.client.client_id, "correct")
        with self.assertRaises(AuthenticationError):
            self.bank.authenticate_client(self.client.client_id, "wrong")
        self.assertEqual(self.client.status, ClientStatus.ACTIVE)

    def test_blocking_is_recorded_in_audit_log(self):
        for _ in range(3):
            with self.assertRaises((AuthenticationError, ClientBlockedError)):
                self.bank.authenticate_client(self.client.client_id, "wrong")
        critical = self.bank.audit_log.filter(severity=AuditSeverity.CRITICAL, category="auth")
        self.assertEqual(len(critical), 1)
        self.assertEqual(critical[0].client_id, self.client.client_id)

    def test_blocked_client_cannot_open_account(self):
        self.client.status = ClientStatus.BLOCKED
        with self.assertRaises(ClientBlockedError):
            self.bank.open_account(self.client.client_id)


if __name__ == "__main__":
    unittest.main()
