import os
import sys
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bank import Bank
from client import Client
from exceptions import (
    CurrencyConversionError,
    InvalidOperationError,
    TransactionNotFoundError,
)
from main import default_rate_provider
from transaction import (
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionStatus,
    TransactionType,
)

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


def deposit(receiver="a", amount=100, **kwargs):
    return Transaction(TransactionType.DEPOSIT, amount, receiver_account_id=receiver, **kwargs)


class TestTransaction(unittest.TestCase):

    def test_unknown_type(self):
        with self.assertRaises(InvalidOperationError):
            Transaction("gift", 100, receiver_account_id="a")

    def test_missing_participants(self):
        with self.assertRaises(InvalidOperationError):
            Transaction(TransactionType.DEPOSIT, 100)
        with self.assertRaises(InvalidOperationError):
            Transaction(TransactionType.WITHDRAWAL, 100)
        with self.assertRaises(InvalidOperationError):
            Transaction(TransactionType.INTERNAL_TRANSFER, 100, sender_account_id="a")

    def test_amount_is_rounded_to_cents(self):
        self.assertEqual(str(deposit(amount=1778).amount), "1778.00")
        self.assertEqual(str(deposit(amount=10.005).amount), "10.01")

    def test_transfer_to_same_account(self):
        with self.assertRaises(InvalidOperationError):
            Transaction(TransactionType.INTERNAL_TRANSFER, 100, sender_account_id="a", receiver_account_id="a")


class TestTransactionQueue(unittest.TestCase):

    def test_higher_priority_comes_first(self):
        queue = TransactionQueue()
        low = deposit(priority=1)
        high = deposit(priority=10)
        queue.add(low)
        queue.add(high)
        self.assertIs(queue.get_next(), high)
        self.assertIs(queue.get_next(), low)

    def test_fifo_within_same_priority(self):
        queue = TransactionQueue()
        first = deposit(priority=1)
        second = deposit(amount=200, priority=1)
        queue.add(first)
        queue.add(second)
        self.assertIs(queue.get_next(), first)
        self.assertIs(queue.get_next(), second)

    def test_cancelled_transaction_is_skipped(self):
        queue = TransactionQueue()
        transaction = deposit()
        queue.add(transaction)
        queue.cancel(transaction.transaction_id)
        self.assertEqual(len(queue), 0)
        self.assertIsNone(queue.get_next())
        self.assertEqual(transaction.status, TransactionStatus.CANCELLED)

    def test_cancel_unknown_transaction(self):
        with self.assertRaises(TransactionNotFoundError):
            TransactionQueue().cancel("missing")

    def test_deferred_transaction_waits_for_its_time(self):
        queue = TransactionQueue()
        now = datetime(2026, 1, 1, 12, 0)
        deferred = deposit(priority=10, scheduled_at=now + timedelta(hours=1))
        ready = deposit(amount=50)
        queue.add(deferred)
        queue.add(ready)

        self.assertIs(queue.get_next(now=now), ready)
        self.assertIsNone(queue.get_next(now=now))
        self.assertEqual(len(queue), 1)
        self.assertIs(queue.get_next(now=now + timedelta(hours=2)), deferred)

    def test_len_reflects_queue_size(self):
        queue = TransactionQueue()
        queue.add(deposit())
        queue.add(deposit(amount=200))
        self.assertEqual(len(queue), 2)

    def test_processed_transaction_cannot_be_added(self):
        transaction = deposit()
        transaction.mark_completed()
        with self.assertRaises(InvalidOperationError):
            TransactionQueue().add(transaction)


class ProcessorTestCase(unittest.TestCase):

    def setUp(self):
        self.bank = make_bank()
        self.alice = make_client(self.bank, "Алина")
        self.bob = make_client(self.bank, "Борис")

    def transfer(self, sender, receiver, amount, transaction_type=TransactionType.INTERNAL_TRANSFER):
        return Transaction(
            transaction_type, amount,
            sender_account_id=sender.account_id,
            receiver_account_id=receiver.account_id,
        )


class TestTransactionProcessorBasics(ProcessorTestCase):

    def test_deposit_succeeds(self):
        account = open_funded_account(self.bank, self.alice)
        transaction = deposit(account.account_id, 1000)
        self.assertTrue(TransactionProcessor(self.bank).process(transaction))
        self.assertEqual(transaction.status, TransactionStatus.COMPLETED)
        self.assertEqual(account.balance, 1000)

    def test_withdrawal_with_insufficient_funds_fails(self):
        account = open_funded_account(self.bank, self.alice)
        transaction = Transaction(TransactionType.WITHDRAWAL, 500, sender_account_id=account.account_id)
        self.assertFalse(TransactionProcessor(self.bank).process(transaction))
        self.assertEqual(transaction.status, TransactionStatus.FAILED)
        self.assertIn("Недостаточно средств", transaction.failure_reason)

    def test_unknown_account_fails(self):
        transaction = deposit("missing", 100)
        processor = TransactionProcessor(self.bank)
        self.assertFalse(processor.process(transaction))
        self.assertEqual(processor.error_log[0]["error_type"], "AccountNotFoundError")

    def test_frozen_account_blocks_transaction(self):
        account = open_funded_account(self.bank, self.alice)
        self.bank.freeze_account(account.account_id)
        transaction = deposit(account.account_id, 100)
        self.assertFalse(TransactionProcessor(self.bank).process(transaction))
        self.assertEqual(transaction.status, TransactionStatus.FAILED)

    def test_processing_time_comes_from_bank_clock(self):
        account = open_funded_account(self.bank, self.alice)
        transaction = deposit(account.account_id, 100)
        TransactionProcessor(self.bank).process(transaction)
        self.assertEqual(transaction.processed_at, DAYTIME)

    def test_transaction_is_processed_only_once(self):
        account = open_funded_account(self.bank, self.alice)
        processor = TransactionProcessor(self.bank)
        transaction = deposit(account.account_id, 100)
        self.assertTrue(processor.process(transaction))
        self.assertFalse(processor.process(transaction))
        self.assertEqual(account.balance, 100)

    def test_internal_transfer(self):
        sender = open_funded_account(self.bank, self.alice, 1000)
        receiver = open_funded_account(self.bank, self.bob)
        transaction = self.transfer(sender, receiver, 300)
        TransactionProcessor(self.bank).process(transaction)
        self.assertEqual(sender.balance, 700)
        self.assertEqual(receiver.balance, 300)
        self.assertEqual(transaction.fee, 0)

    def test_external_transfer_charges_fee(self):
        sender = open_funded_account(self.bank, self.alice, 1000)
        receiver = open_funded_account(self.bank, self.bob)
        transaction = self.transfer(sender, receiver, 300, TransactionType.EXTERNAL_TRANSFER)
        TransactionProcessor(self.bank).process(transaction)
        self.assertEqual(transaction.fee, 3)
        self.assertEqual(sender.balance, 697)
        self.assertEqual(receiver.balance, 300)

    def test_premium_account_can_transfer_into_overdraft(self):
        sender = open_funded_account(self.bank, self.alice, account_type="premium", overdraft_limit=500)
        receiver = open_funded_account(self.bank, self.bob)
        transaction = self.transfer(sender, receiver, 300)
        self.assertTrue(TransactionProcessor(self.bank).process(transaction))
        self.assertLess(sender.balance, 0)

    def test_regular_account_cannot_transfer_into_overdraft(self):
        sender = open_funded_account(self.bank, self.alice, 100)
        receiver = open_funded_account(self.bank, self.bob)
        self.assertFalse(TransactionProcessor(self.bank).process(self.transfer(sender, receiver, 300)))
        self.assertEqual(sender.balance, 100)

    def test_currency_conversion(self):
        sender = open_funded_account(self.bank, self.alice, 1000, currency="USD")
        receiver = open_funded_account(self.bank, self.bob, currency="RUB")
        TransactionProcessor(self.bank).process(self.transfer(sender, receiver, 100))
        self.assertEqual(sender.balance, 900)
        self.assertEqual(receiver.balance, 9500)

    def test_default_rate_provider_covers_all_currencies(self):
        self.assertEqual(default_rate_provider("KZT", "KZT"), 1)
        self.assertGreater(default_rate_provider("CNY", "KZT"), 0)


class TestTransactionProcessorSafety(ProcessorTestCase):

    def test_night_restriction_applies_to_queued_transactions(self):
        bank = make_bank(now=NIGHT)
        client = make_client(bank)
        account = bank.open_account(client.client_id)
        transaction = deposit(account.account_id, 100)
        processor = TransactionProcessor(bank)
        self.assertFalse(processor.process(transaction))
        self.assertEqual(processor.error_log[0]["error_type"], "NightOperationRestrictedError")
        self.assertEqual(account.balance, 0)

    def test_sender_is_not_debited_when_receiver_is_frozen(self):
        sender = open_funded_account(self.bank, self.alice, 1000)
        receiver = open_funded_account(self.bank, self.bob)
        self.bank.freeze_account(receiver.account_id)
        processor = TransactionProcessor(self.bank)
        self.assertFalse(processor.process(self.transfer(sender, receiver, 300)))
        self.assertEqual(sender.balance, 1000)

    def test_sender_is_not_debited_when_credit_exceeds_receiver_limit(self):
        sender = open_funded_account(self.bank, self.alice, 2000, currency="USD")
        receiver = open_funded_account(self.bank, self.bob, currency="RUB")
        processor = TransactionProcessor(self.bank)
        self.assertFalse(processor.process(self.transfer(sender, receiver, 1500)))
        self.assertEqual(sender.balance, 2000)
        self.assertEqual(receiver.balance, 0)


class TestTransactionProcessorRetries(ProcessorTestCase):

    def setUp(self):
        super().setUp()
        self.sender = open_funded_account(self.bank, self.alice, 1000, currency="USD")
        self.receiver = open_funded_account(self.bank, self.bob, currency="RUB")

    def test_retries_until_rate_is_available_without_double_debit(self):
        calls = []

        def flaky_rate_provider(from_currency, to_currency):
            calls.append((from_currency, to_currency))
            if len(calls) < 3:
                raise CurrencyConversionError("Сервис курсов временно недоступен.")
            return 95.0

        processor = TransactionProcessor(self.bank, rate_provider=flaky_rate_provider, max_retries=5)
        transaction = self.transfer(self.sender, self.receiver, 100)

        self.assertTrue(processor.process(transaction))
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(processor.error_log), 2)
        self.assertEqual(self.sender.balance, 900)
        self.assertEqual(self.receiver.balance, 9500)

    def test_fails_after_max_retries_without_debit(self):
        def failing_rate_provider(from_currency, to_currency):
            raise CurrencyConversionError("Сервис курсов недоступен.")

        processor = TransactionProcessor(self.bank, rate_provider=failing_rate_provider, max_retries=3)
        transaction = self.transfer(self.sender, self.receiver, 100)

        self.assertFalse(processor.process(transaction))
        self.assertEqual(transaction.status, TransactionStatus.FAILED)
        self.assertEqual(len(processor.error_log), 3)
        self.assertEqual(self.sender.balance, 1000)
        self.assertEqual(self.receiver.balance, 0)

    def test_max_retries_must_be_positive(self):
        with self.assertRaises(InvalidOperationError):
            TransactionProcessor(self.bank, max_retries=0)


class TestTransactionBatch(ProcessorTestCase):

    def test_ten_transactions_through_queue_and_processor(self):
        sender = open_funded_account(self.bank, self.alice, 100_000)
        receiver = open_funded_account(self.bank, self.bob, 100_000)
        queue = TransactionQueue()
        for i in range(10):
            queue.add(Transaction(
                TransactionType.INTERNAL_TRANSFER, 100 + i,
                sender_account_id=sender.account_id,
                receiver_account_id=receiver.account_id,
                priority=i,
            ))
        self.assertEqual(len(queue), 10)

        processor = TransactionProcessor(self.bank)
        processed = []
        while (transaction := queue.get_next()) is not None:
            processor.process(transaction)
            processed.append(transaction)

        self.assertEqual(len(processed), 10)
        self.assertEqual(len(queue), 0)
        self.assertEqual([t.priority for t in processed], list(range(9, -1, -1)))
        self.assertTrue(all(t.status == TransactionStatus.COMPLETED for t in processed))
        self.assertEqual(sender.balance + receiver.balance, 200_000)


if __name__ == "__main__":
    unittest.main()