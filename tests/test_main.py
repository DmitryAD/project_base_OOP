import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import BankAccount, AccountStatus
from exceptions import (
    AccountFrozenError,
    AccountClosedError,
    InvalidOperationError,
    InsufficientFundsError,
)


class TestBankAccount(unittest.TestCase):

    def test_create_active_account(self):
        acc = BankAccount(owner="Тест Тестов", currency="RUB")
        self.assertEqual(acc.get_account_info()["status"], AccountStatus.ACTIVE)

    def test_invalid_currency(self):
        with self.assertRaises(InvalidOperationError):
            BankAccount(owner="Тест", currency="XXX")

    def test_deposit_and_withdraw(self):
        acc = BankAccount(owner="Тест", currency="USD")
        acc.deposit(500)
        acc.withdraw(200)
        self.assertEqual(acc.get_account_info()["balance"], 300)

    def test_negative_amount(self):
        acc = BankAccount(owner="Тест", currency="EUR")
        with self.assertRaises(InvalidOperationError):
            acc.deposit(-50)

    def test_frozen_account_blocks_operations(self):
        acc = BankAccount(owner="Тест", currency="RUB")
        acc.freeze()
        with self.assertRaises(AccountFrozenError):
            acc.deposit(100)

    def test_closed_account_blocks_operations(self):
        acc = BankAccount(owner="Тест", currency="RUB")
        acc.close()
        with self.assertRaises(AccountClosedError):
            acc.withdraw(10)

    def test_insufficient_funds(self):
        acc = BankAccount(owner="Тест", currency="RUB")
        acc.deposit(100)
        with self.assertRaises(InsufficientFundsError):
            acc.withdraw(500)


if __name__ == "__main__":
    unittest.main()
