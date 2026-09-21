import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)
from main import (
    AccountStatus,
    BankAccount,
    InvestmentAccount,
    PremiumAccount,
    SavingsAccount,
    round_money,
    to_decimal,
)


class TestToDecimal(unittest.TestCase):

    def test_float_is_converted_via_string(self):
        self.assertEqual(to_decimal(0.1), Decimal("0.1"))

    def test_decimal_sum_is_exact(self):
        self.assertEqual(to_decimal(0.1) + to_decimal(0.2), Decimal("0.3"))

    def test_bool_is_rejected(self):
        with self.assertRaises(InvalidOperationError):
            to_decimal(True)

    def test_string_is_rejected(self):
        with self.assertRaises(InvalidOperationError):
            to_decimal("100")

    def test_infinity_and_nan_are_rejected(self):
        for value in (float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(InvalidOperationError):
                to_decimal(value)


class TestRoundMoney(unittest.TestCase):

    def test_rounds_half_up_to_cents(self):
        self.assertEqual(round_money(Decimal("2.345")), Decimal("2.35"))
        self.assertEqual(round_money(Decimal("2.344")), Decimal("2.34"))


class TestBankAccount(unittest.TestCase):

    def test_new_account_is_active_with_zero_balance(self):
        account = BankAccount(owner="Тест Тестов", currency="RUB")
        self.assertEqual(account.status, AccountStatus.ACTIVE)
        self.assertEqual(account.balance, 0)

    def test_account_id_is_generated(self):
        account = BankAccount(owner="Тест")
        self.assertEqual(len(account.account_id), 8)

    def test_invalid_currency(self):
        with self.assertRaises(InvalidOperationError):
            BankAccount(owner="Тест", currency="XXX")

    def test_empty_owner(self):
        with self.assertRaises(InvalidOperationError):
            BankAccount(owner="  ")

    def test_deposit_and_withdraw(self):
        account = BankAccount(owner="Тест", currency="USD")
        account.deposit(500)
        account.withdraw(200)
        self.assertEqual(account.balance, 300)

    def test_float_amounts_are_exact(self):
        account = BankAccount(owner="Тест")
        account.deposit(0.1)
        account.deposit(0.2)
        self.assertEqual(account.balance, Decimal("0.30"))

    def test_invalid_amounts(self):
        account = BankAccount(owner="Тест")
        for amount in (-50, 0, True, "100", 0.001):
            with self.subTest(amount=amount), self.assertRaises(InvalidOperationError):
                account.deposit(amount)

    def test_frozen_account_blocks_operations(self):
        account = BankAccount(owner="Тест")
        account.freeze()
        with self.assertRaises(AccountFrozenError):
            account.deposit(100)

    def test_closed_account_blocks_operations(self):
        account = BankAccount(owner="Тест")
        account.close()
        with self.assertRaises(AccountClosedError):
            account.withdraw(10)

    def test_closed_account_cannot_be_frozen_or_reopened(self):
        account = BankAccount(owner="Тест")
        account.close()
        with self.assertRaises(AccountClosedError):
            account.freeze()
        with self.assertRaises(AccountClosedError):
            account.unfreeze()
        self.assertEqual(account.status, AccountStatus.CLOSED)

    def test_insufficient_funds(self):
        account = BankAccount(owner="Тест")
        account.deposit(100)
        with self.assertRaises(InsufficientFundsError):
            account.withdraw(500)

    def test_validate_deposit_does_not_change_balance(self):
        account = BankAccount(owner="Тест")
        self.assertEqual(account.validate_deposit(100), 100)
        self.assertEqual(account.balance, 0)

    def test_default_transaction_limit(self):
        account = BankAccount(owner="Тест")
        self.assertEqual(account.max_transaction_limit, 100_000)

    def test_deposit_above_limit_raises_error(self):
        account = BankAccount(owner="Тест")
        with self.assertRaises(InvalidOperationError):
            account.deposit(200_000)

    def test_custom_transaction_limit_is_inclusive(self):
        account = BankAccount(owner="Тест", max_transaction_limit=500)
        account.deposit(500)
        with self.assertRaises(InvalidOperationError):
            account.deposit(501)

    def test_info_contains_type(self):
        self.assertEqual(BankAccount(owner="Тест").get_account_info()["type"], "BankAccount")

    def test_str_shows_last_four_digits(self):
        account = BankAccount(owner="Тест", account_id="12345678")
        self.assertIn("****5678", str(account))


class TestSavingsAccount(unittest.TestCase):

    def make_account(self, **options):
        params = {"owner": "Анна", "min_balance": 1000, "monthly_rate": 0.03}
        params.update(options)
        return SavingsAccount(**params)

    def test_cannot_withdraw_below_min_balance(self):
        account = self.make_account()
        account.deposit(5000)
        with self.assertRaises(InsufficientFundsError):
            account.withdraw(4500)

    def test_withdraw_down_to_min_balance_is_allowed(self):
        account = self.make_account()
        account.deposit(5000)
        account.withdraw(4000)
        self.assertEqual(account.balance, 1000)

    def test_apply_monthly_interest(self):
        account = self.make_account(min_balance=0, monthly_rate=0.10)
        account.deposit(1000)
        self.assertEqual(account.apply_monthly_interest(), 100)
        self.assertEqual(account.balance, 1100)

    def test_interest_is_rounded_to_cents(self):
        account = self.make_account(min_balance=0, monthly_rate=0.015)
        account.deposit(333.33)
        self.assertEqual(account.apply_monthly_interest(), Decimal("5.00"))

    def test_account_info_contains_savings_fields(self):
        info = self.make_account(min_balance=500, monthly_rate=0.02).get_account_info()
        self.assertEqual(info["type"], "SavingsAccount")
        self.assertEqual(info["min_balance"], 500)
        self.assertEqual(info["monthly_rate"], Decimal("0.02"))

    def test_inherits_default_transaction_limit(self):
        self.assertEqual(self.make_account().max_transaction_limit, 100_000)

    def test_accepts_custom_transaction_limit(self):
        account = self.make_account(max_transaction_limit=300_000)
        account.deposit(250_000)
        self.assertEqual(account.balance, 250_000)


class TestPremiumAccount(unittest.TestCase):

    def test_overdraft_is_allowed_within_limit(self):
        account = PremiumAccount(owner="Олег", currency="USD", overdraft_limit=1000, withdrawal_fee=10)
        account.deposit(200)
        account.withdraw(500)
        self.assertEqual(account.balance, -310)

    def test_overdraft_limit_exceeded(self):
        account = PremiumAccount(owner="Олег", currency="USD", overdraft_limit=100, withdrawal_fee=10)
        account.deposit(50)
        with self.assertRaises(InsufficientFundsError):
            account.withdraw(200)

    def test_withdrawal_fee_is_deducted(self):
        account = PremiumAccount(owner="Олег", currency="USD", overdraft_limit=1000, withdrawal_fee=25)
        account.deposit(1000)
        account.withdraw(100)
        self.assertEqual(account.balance, 875)

    def test_has_higher_default_limit_than_bank_account(self):
        self.assertGreater(
            PremiumAccount(owner="Олег").max_transaction_limit,
            BankAccount(owner="Тест").max_transaction_limit,
        )

    def test_blocks_operation_above_own_limit(self):
        account = PremiumAccount(owner="Олег", max_transaction_limit=2000)
        with self.assertRaises(InvalidOperationError):
            account.deposit(5000)


class TestInvestmentAccount(unittest.TestCase):

    def test_buy_asset_moves_money_to_portfolio(self):
        account = InvestmentAccount(owner="Мария")
        account.deposit(10000)
        account.buy_asset("stocks", 4000)
        self.assertEqual(account.balance, 6000)
        self.assertEqual(account.portfolio["stocks"], 4000)

    def test_portfolio_cannot_be_changed_from_outside(self):
        account = InvestmentAccount(owner="Мария")
        account.portfolio["stocks"] = 1_000_000
        self.assertEqual(account.portfolio["stocks"], 0)

    def test_buy_unknown_asset(self):
        account = InvestmentAccount(owner="Мария")
        account.deposit(1000)
        with self.assertRaises(InvalidOperationError):
            account.buy_asset("crypto", 100)

    def test_withdraw_ignores_portfolio(self):
        account = InvestmentAccount(owner="Мария")
        account.deposit(1000)
        account.buy_asset("bonds", 800)
        with self.assertRaises(InsufficientFundsError):
            account.withdraw(500)

    def test_project_yearly_growth(self):
        account = InvestmentAccount(owner="Мария")
        account.deposit(1000)
        account.buy_asset("stocks", 1000)
        growth = account.project_yearly_growth()
        self.assertEqual(growth["stocks"], Decimal("1100.00"))
        self.assertEqual(growth["bonds"], 0)
        self.assertEqual(growth["etf"], 0)


if __name__ == "__main__":
    unittest.main()
