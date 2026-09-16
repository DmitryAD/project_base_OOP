import sys
import os
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bank import Bank
from client import Client
from transaction import (
    Transaction,
    TransactionType,
    TransactionStatus,
    TransactionQueue,
    TransactionProcessor,
    CurrencyConversionError,
)
from exceptions import TransactionNotFoundError


def make_bank():
    return Bank(name="TestBank")


def make_client(bank, name="Тест"):
    return bank.add_client(Client(full_name=name, birth_date=date(1990, 1, 1), password="pass"))


class TestTransactionQueue(unittest.TestCase):

    def test_higher_priority_comes_first(self):
        queue = TransactionQueue()
        low = Transaction(TransactionType.DEPOSIT, 100, receiver_account_id="a", priority=1)
        high = Transaction(TransactionType.DEPOSIT, 100, receiver_account_id="a", priority=10)
        queue.add(low)
        queue.add(high)

        self.assertEqual(queue.get_next(), high)
        self.assertEqual(queue.get_next(), low)

    def test_fifo_within_same_priority(self):
        queue = TransactionQueue()
        first = Transaction(TransactionType.DEPOSIT, 100, receiver_account_id="a", priority=1)
        second = Transaction(TransactionType.DEPOSIT, 200, receiver_account_id="a", priority=1)
        queue.add(first)
        queue.add(second)

        self.assertEqual(queue.get_next(), first)
        self.assertEqual(queue.get_next(), second)

    def test_cancel_skips_transaction_on_get_next(self):
        queue = TransactionQueue()
        transaction = Transaction(TransactionType.DEPOSIT, 100, receiver_account_id="a", priority=1)
        queue.add(transaction)
        queue.cancel(transaction.transaction_id)

        self.assertIsNone(queue.get_next())
        self.assertEqual(transaction.status, TransactionStatus.CANCELLED)

    def test_cancel_unknown_transaction_raises_error(self):
        queue = TransactionQueue()
        with self.assertRaises(TransactionNotFoundError):
            queue.cancel("не существует")

    def test_deferred_transaction_not_returned_before_scheduled_time(self):
        queue = TransactionQueue()
        future_time = datetime.now() + timedelta(hours=1)
        deferred = Transaction(TransactionType.DEPOSIT, 100, receiver_account_id="a", scheduled_at=future_time)
        ready = Transaction(TransactionType.DEPOSIT, 50, receiver_account_id="a")
        queue.add(deferred)
        queue.add(ready)

        # deferred ещё не наступила -> должна вернуться готовая транзакция
        self.assertEqual(queue.get_next(), ready)

    def test_len_reflects_queue_size(self):
        queue = TransactionQueue()
        queue.add(Transaction(TransactionType.DEPOSIT, 100, receiver_account_id="a"))
        queue.add(Transaction(TransactionType.DEPOSIT, 200, receiver_account_id="a"))
        self.assertEqual(len(queue), 2)


class TestTransactionProcessorBasics(unittest.TestCase):

    def test_deposit_succeeds(self):
        bank = make_bank()
        client = make_client(bank)
        account = bank.open_account(client.client_id, currency="RUB")
        processor = TransactionProcessor(bank)

        transaction = Transaction(TransactionType.DEPOSIT, 1000, receiver_account_id=account.get_account_info()["account_id"])
        result = processor.process(transaction)

        self.assertTrue(result)
        self.assertEqual(transaction.status, TransactionStatus.COMPLETED)
        self.assertEqual(account.get_account_info()["balance"], 1000)

    def test_withdrawal_with_insufficient_funds_fails_permanently(self):
        bank = make_bank()
        client = make_client(bank)
        account = bank.open_account(client.client_id, currency="RUB")
        processor = TransactionProcessor(bank)

        transaction = Transaction(TransactionType.WITHDRAWAL, 500, sender_account_id=account.get_account_info()["account_id"])
        result = processor.process(transaction)

        self.assertFalse(result)
        self.assertEqual(transaction.status, TransactionStatus.FAILED)
        self.assertIn("Недостаточно средств", transaction.failure_reason)

    def test_frozen_account_blocks_transaction(self):
        bank = make_bank()
        client = make_client(bank)
        account = bank.open_account(client.client_id, currency="RUB")
        bank.freeze_account(account.get_account_info()["account_id"])
        processor = TransactionProcessor(bank)

        transaction = Transaction(TransactionType.DEPOSIT, 100, receiver_account_id=account.get_account_info()["account_id"])
        result = processor.process(transaction)

        self.assertFalse(result)
        self.assertEqual(transaction.status, TransactionStatus.FAILED)

    def test_internal_transfer_moves_money_between_accounts(self):
        bank = make_bank()
        alice = make_client(bank, "Алина")
        bob = make_client(bank, "Борис")
        acc_a = bank.open_account(alice.client_id, currency="RUB")
        acc_b = bank.open_account(bob.client_id, currency="RUB")
        bank.deposit_to_account(acc_a.get_account_info()["account_id"], 1000)
        processor = TransactionProcessor(bank)

        transaction = Transaction(
            TransactionType.INTERNAL_TRANSFER, 300,
            sender_account_id=acc_a.get_account_info()["account_id"],
            receiver_account_id=acc_b.get_account_info()["account_id"],
        )
        processor.process(transaction)

        self.assertEqual(acc_a.get_account_info()["balance"], 700)
        self.assertEqual(acc_b.get_account_info()["balance"], 300)
        self.assertEqual(transaction.fee, 0.0)

    def test_external_transfer_charges_fee(self):
        bank = make_bank()
        alice = make_client(bank, "Алина")
        bob = make_client(bank, "Борис")
        acc_a = bank.open_account(alice.client_id, currency="RUB")
        acc_b = bank.open_account(bob.client_id, currency="RUB")
        bank.deposit_to_account(acc_a.get_account_info()["account_id"], 1000)
        processor = TransactionProcessor(bank)

        transaction = Transaction(
            TransactionType.EXTERNAL_TRANSFER, 300,
            sender_account_id=acc_a.get_account_info()["account_id"],
            receiver_account_id=acc_b.get_account_info()["account_id"],
        )
        processor.process(transaction)

        # комиссия 1% от 300 = 3.0 -> списано 303, зачислено 300
        self.assertEqual(transaction.fee, 3.0)
        self.assertEqual(acc_a.get_account_info()["balance"], 1000 - 303)
        self.assertEqual(acc_b.get_account_info()["balance"], 300)

    def test_premium_account_allows_transfer_into_overdraft(self):
        bank = make_bank()
        alice = make_client(bank, "Алина")
        bob = make_client(bank, "Борис")
        acc_a = bank.open_account(alice.client_id, account_type="premium", currency="RUB", overdraft_limit=500)
        acc_b = bank.open_account(bob.client_id, currency="RUB")
        processor = TransactionProcessor(bank)

        transaction = Transaction(
            TransactionType.INTERNAL_TRANSFER, 300,
            sender_account_id=acc_a.get_account_info()["account_id"],
            receiver_account_id=acc_b.get_account_info()["account_id"],
        )
        result = processor.process(transaction)

        self.assertTrue(result)
        self.assertLess(acc_a.get_account_info()["balance"], 0)


class TestTransactionProcessorRetries(unittest.TestCase):

    def test_currency_conversion_retries_and_eventually_succeeds(self):
        bank = make_bank()
        alice = make_client(bank, "Алина")
        bob = make_client(bank, "Борис")
        acc_a = bank.open_account(alice.client_id, currency="USD")
        acc_b = bank.open_account(bob.client_id, currency="RUB")
        bank.deposit_to_account(acc_a.get_account_info()["account_id"], 1000)

        call_count = {"n": 0}

        def flaky_rate_provider(from_currency, to_currency):
            """Падает первые 2 раза, срабатывает на 3-ю попытку."""
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise CurrencyConversionError("Сервис курсов временно недоступен.")
            return 95.0

        processor = TransactionProcessor(bank, rate_provider=flaky_rate_provider, max_retries=5)
        transaction = Transaction(
            TransactionType.INTERNAL_TRANSFER, 100,
            sender_account_id=acc_a.get_account_info()["account_id"],
            receiver_account_id=acc_b.get_account_info()["account_id"],
        )
        result = processor.process(transaction)

        self.assertTrue(result)
        self.assertEqual(call_count["n"], 3)
        self.assertEqual(len(processor.error_log), 2)  # 2 неудачные попытки залогированы

    def test_currency_conversion_fails_after_max_retries(self):
        bank = make_bank()
        alice = make_client(bank, "Алина")
        bob = make_client(bank, "Борис")
        acc_a = bank.open_account(alice.client_id, currency="USD")
        acc_b = bank.open_account(bob.client_id, currency="RUB")
        bank.deposit_to_account(acc_a.get_account_info()["account_id"], 1000)

        def always_failing_rate_provider(from_currency, to_currency):
            raise CurrencyConversionError("Сервис курсов недоступен.")

        processor = TransactionProcessor(bank, rate_provider=always_failing_rate_provider, max_retries=3)
        transaction = Transaction(
            TransactionType.INTERNAL_TRANSFER, 100,
            sender_account_id=acc_a.get_account_info()["account_id"],
            receiver_account_id=acc_b.get_account_info()["account_id"],
        )
        result = processor.process(transaction)

        self.assertFalse(result)
        self.assertEqual(transaction.status, TransactionStatus.FAILED)
        self.assertEqual(len(processor.error_log), 3)


class TestTenTransactionsBatch(unittest.TestCase):

    def test_ten_transactions_through_queue_and_processor(self):
        """Прогоняет 10 транзакций через очередь и процессор целиком — то, что явно требует задание Дня 4."""
        bank = make_bank()
        alice = make_client(bank, "Алина")
        bob = make_client(bank, "Борис")
        acc_a = bank.open_account(alice.client_id, currency="RUB")
        acc_b = bank.open_account(bob.client_id, currency="RUB")
        bank.deposit_to_account(acc_a.get_account_info()["account_id"], 100000)
        bank.deposit_to_account(acc_b.get_account_info()["account_id"], 100000)

        a_id = acc_a.get_account_info()["account_id"]
        b_id = acc_b.get_account_info()["account_id"]

        queue = TransactionQueue()
        for i in range(10):
            queue.add(Transaction(TransactionType.INTERNAL_TRANSFER, 100 + i, sender_account_id=a_id, receiver_account_id=b_id, priority=i))

        self.assertEqual(len(queue), 10)

        processor = TransactionProcessor(bank)
        processed = 0
        while True:
            transaction = queue.get_next()
            if transaction is None:
                break
            processor.process(transaction)
            processed += 1

        self.assertEqual(processed, 10)
        self.assertEqual(len(queue), 0)


if __name__ == "__main__":
    unittest.main()
