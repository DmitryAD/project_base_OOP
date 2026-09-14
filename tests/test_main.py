import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import (
    BankAccount,
    AccountStatus,
    SavingsAccount,
    PremiumAccount,
    InvestmentAccount,
)
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

    # === НОВОЕ ===
    def test_default_transaction_limit_is_100000(self):
        acc = BankAccount(owner="Тест", currency="RUB")
        self.assertEqual(acc.max_transaction_limit, 100_000.0)

    def test_deposit_above_limit_raises_error(self):
        acc = BankAccount(owner="Тест", currency="RUB")
        with self.assertRaises(InvalidOperationError):
            acc.deposit(200_000)

    def test_custom_transaction_limit(self):
        acc = BankAccount(owner="Тест", currency="RUB", max_transaction_limit=500)
        acc.deposit(500)  # ровно на границе — разрешено
        with self.assertRaises(InvalidOperationError):
            acc.deposit(501)
    # === КОНЕЦ НОВОГО ===


class TestSavingsAccount(unittest.TestCase):

    def test_cannot_withdraw_below_min_balance(self):
        acc = SavingsAccount(owner="Анна", currency="RUB", min_balance=1000, monthly_rate=0.03)
        acc.deposit(5000)
        with self.assertRaises(InsufficientFundsError):
            acc.withdraw(4500)

    def test_withdraw_down_to_min_balance_is_allowed(self):
        acc = SavingsAccount(owner="Анна", currency="RUB", min_balance=1000, monthly_rate=0.03)
        acc.deposit(5000)
        acc.withdraw(4000)
        self.assertEqual(acc.get_account_info()["balance"], 1000)

    def test_apply_monthly_interest(self):
        acc = SavingsAccount(owner="Анна", currency="RUB", min_balance=0, monthly_rate=0.10)
        acc.deposit(1000)
        interest = acc.apply_monthly_interest()
        self.assertEqual(interest, 100)
        self.assertEqual(acc.get_account_info()["balance"], 1100)

    def test_get_account_info_contains_savings_fields(self):
        acc = SavingsAccount(owner="Анна", currency="RUB", min_balance=500, monthly_rate=0.02)
        info = acc.get_account_info()
        self.assertEqual(info["type"], "SavingsAccount")
        self.assertEqual(info["min_balance"], 500)
        self.assertEqual(info["monthly_rate"], 0.02)

    # === НОВОЕ ===
    def test_savings_inherits_default_transaction_limit(self):
        # SavingsAccount не передаёт свой max_transaction_limit, значит
        # должен получить значение по умолчанию от BankAccount (100_000)
        acc = SavingsAccount(owner="Анна", currency="RUB")
        self.assertEqual(acc.max_transaction_limit, 100_000.0)
    # === КОНЕЦ НОВОГО ===


class TestPremiumAccount(unittest.TestCase):

    def test_overdraft_is_allowed_within_limit(self):
        acc = PremiumAccount(owner="Олег", currency="USD", overdraft_limit=1000, withdrawal_fee=10)
        acc.deposit(200)
        acc.withdraw(500)
        self.assertEqual(acc.get_account_info()["balance"], -310)

    def test_overdraft_limit_exceeded_raises_error(self):
        acc = PremiumAccount(owner="Олег", currency="USD", overdraft_limit=100, withdrawal_fee=10)
        acc.deposit(50)
        with self.assertRaises(InsufficientFundsError):
            acc.withdraw(200)

    def test_withdrawal_fee_is_deducted(self):
        acc = PremiumAccount(owner="Олег", currency="USD", overdraft_limit=1000, withdrawal_fee=25)
        acc.deposit(1000)
        acc.withdraw(100)
        self.assertEqual(acc.get_account_info()["balance"], 875)

    # === НОВОЕ ===
    def test_premium_has_higher_default_limit_than_bank_account(self):
        base = BankAccount(owner="Тест", currency="RUB")
        premium = PremiumAccount(owner="Олег", currency="RUB")
        self.assertGreater(premium.max_transaction_limit, base.max_transaction_limit)

    def test_premium_still_blocks_operation_above_its_own_limit(self):
        premium = PremiumAccount(owner="Олег", currency="RUB", max_transaction_limit=2000)
        with self.assertRaises(InvalidOperationError):
            premium.deposit(5000)
    # === КОНЕЦ НОВОГО ===


class TestInvestmentAccount(unittest.TestCase):

    def test_buy_asset_moves_money_from_balance_to_portfolio(self):
        acc = InvestmentAccount(owner="Мария", currency="RUB")
        acc.deposit(10000)
        acc.buy_asset("stocks", 4000)
        self.assertEqual(acc.get_account_info()["balance"], 6000)
        self.assertEqual(acc.portfolio["stocks"], 4000)

    def test_buy_unknown_asset_raises_error(self):
        acc = InvestmentAccount(owner="Мария", currency="RUB")
        acc.deposit(1000)
        with self.assertRaises(InvalidOperationError):
            acc.buy_asset("crypto", 100)

    def test_withdraw_ignores_portfolio(self):
        acc = InvestmentAccount(owner="Мария", currency="RUB")
        acc.deposit(1000)
        acc.buy_asset("bonds", 800)
        with self.assertRaises(InsufficientFundsError):
            acc.withdraw(500)

    def test_project_yearly_growth_calculates_correctly(self):
        acc = InvestmentAccount(owner="Мария", currency="RUB")
        acc.deposit(1000)
        acc.buy_asset("stocks", 1000)
        growth = acc.project_yearly_growth()
        self.assertAlmostEqual(growth["stocks"], 1100.0)
        self.assertAlmostEqual(growth["bonds"], 0.0)
        self.assertAlmostEqual(growth["etf"], 0.0)


if __name__ == "__main__":
    unittest.main()
