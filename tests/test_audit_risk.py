import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from audit import AuditLog, AuditSeverity
from bank import Bank
from client import Client
from exceptions import SuspiciousOperationBlockedError
from risk import RiskAnalyzer, RiskLevel
from transaction import Transaction, TransactionProcessor, TransactionType

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


class TestAuditLog(unittest.TestCase):

    def test_record_stores_event_in_memory(self):
        log = AuditLog()
        log.record(AuditSeverity.INFO, "test", "сообщение")
        self.assertEqual(len(log), 1)

    def test_filter_by_severity_client_and_category(self):
        log = AuditLog()
        log.record(AuditSeverity.INFO, "auth", "обычное", client_id="c1")
        log.record(AuditSeverity.CRITICAL, "risk", "опасное", client_id="c2")
        self.assertEqual([e.message for e in log.filter(severity=AuditSeverity.CRITICAL)], ["опасное"])
        self.assertEqual(len(log.filter(client_id="c1")), 1)
        self.assertEqual(len(log.filter(category="risk")), 1)
        self.assertEqual(len(log.filter()), 2)

    def test_filter_since(self):
        times = iter([datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 11, 0)])
        log = AuditLog(time_provider=lambda: next(times))
        log.record(AuditSeverity.INFO, "test", "раннее")
        log.record(AuditSeverity.INFO, "test", "позднее")
        recent = log.filter(since=datetime(2026, 1, 1, 10, 30))
        self.assertEqual([e.message for e in recent], ["позднее"])

    def test_events_are_written_to_file_as_json_lines(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "audit.jsonl"
            log = AuditLog(file_path=str(path))
            log.record(AuditSeverity.WARNING, "risk", "первое", amount=Decimal("100.50"))
            log.record(AuditSeverity.INFO, "risk", "второе")
            lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first["message"], "первое")
        self.assertEqual(first["details"]["amount"], "100.50")


class TestRiskAnalyzer(unittest.TestCase):

    def analyzer(self, now=DAYTIME):
        return RiskAnalyzer(time_provider=lambda: now)

    def test_normal_operation_is_low_risk(self):
        level, reasons = self.analyzer().analyze(1000, [], is_new_receiver=False)
        self.assertEqual(level, RiskLevel.LOW)
        self.assertEqual(reasons, [])

    def test_large_amount_alone_is_medium_risk(self):
        level, _ = self.analyzer().analyze(600_000, [], is_new_receiver=False)
        self.assertEqual(level, RiskLevel.MEDIUM)

    def test_large_amount_at_night_is_high_risk(self):
        level, reasons = self.analyzer(NIGHT).analyze(600_000, [], is_new_receiver=False)
        self.assertEqual(level, RiskLevel.HIGH)
        self.assertEqual(len(reasons), 2)

    def test_frequent_operations_detected(self):
        recent = [DAYTIME - timedelta(minutes=1)] * 5
        level, reasons = self.analyzer().analyze(100, recent, is_new_receiver=False)
        self.assertEqual(level, RiskLevel.MEDIUM)
        self.assertIn("частые операции", reasons[0])

    def test_old_operations_are_not_counted(self):
        old = [DAYTIME - timedelta(hours=1)] * 10
        level, _ = self.analyzer().analyze(100, old, is_new_receiver=False)
        self.assertEqual(level, RiskLevel.LOW)

    def test_new_receiver_detected(self):
        level, _ = self.analyzer().analyze(100, [], is_new_receiver=True)
        self.assertEqual(level, RiskLevel.MEDIUM)


class TestBankRiskIntegration(unittest.TestCase):

    def setUp(self):
        self.bank = make_bank()
        self.client = make_client(self.bank)
        self.account = open_funded_account(
            self.bank, self.client, 1_000_000, max_transaction_limit=2_000_000,
        )

    def withdraw(self, amount):
        return self.bank.withdraw_from_account(self.account.account_id, self.client.client_id, amount)

    def make_frequent_operations(self):
        for _ in range(RiskAnalyzer.FREQUENT_OPERATIONS_THRESHOLD):
            self.withdraw(100)

    def test_normal_withdrawal_is_not_blocked(self):
        self.assertEqual(self.withdraw(1000), 999_000)

    def test_high_risk_withdrawal_is_blocked_and_balance_is_unchanged(self):
        self.make_frequent_operations()
        balance_before = self.account.balance
        with self.assertRaises(SuspiciousOperationBlockedError):
            self.withdraw(600_000)
        self.assertEqual(self.account.balance, balance_before)

    def test_blocked_operation_is_logged_as_critical(self):
        self.make_frequent_operations()
        with self.assertRaises(SuspiciousOperationBlockedError):
            self.withdraw(600_000)
        report = self.bank.get_suspicious_operations_report()
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0].severity, AuditSeverity.CRITICAL)

    def test_client_risk_profile_counts_by_level(self):
        self.withdraw(100)
        self.withdraw(600_000)
        profile = self.bank.get_client_risk_profile(self.client.client_id)
        self.assertEqual(profile["total_operations"], 2)
        self.assertEqual(profile[RiskLevel.LOW], 1)
        self.assertEqual(profile[RiskLevel.MEDIUM], 1)
        self.assertEqual(profile[RiskLevel.HIGH], 0)

    def test_blocked_transfer_does_not_make_receiver_known(self):
        other = make_client(self.bank, "Получатель")
        receiver = open_funded_account(self.bank, other)
        with self.assertRaises(SuspiciousOperationBlockedError):
            self.bank.check_operation_risk(self.client.client_id, 600_000, receiver.account_id)
        level = self.bank.check_operation_risk(self.client.client_id, 100, receiver.account_id)
        self.assertEqual(level, RiskLevel.MEDIUM)

    def test_processor_blocks_high_risk_transfer(self):
        other = make_client(self.bank, "Получатель")
        receiver = open_funded_account(self.bank, other, account_type="premium")
        transaction = Transaction(
            TransactionType.INTERNAL_TRANSFER, 600_000,
            sender_account_id=self.account.account_id,
            receiver_account_id=receiver.account_id,
        )
        processor = TransactionProcessor(self.bank)
        self.assertFalse(processor.process(transaction))
        self.assertEqual(self.bank.get_error_statistics(processor.error_log), {
            "SuspiciousOperationBlockedError": 1,
        })
        self.assertEqual(self.account.balance, 1_000_000)


if __name__ == "__main__":
    unittest.main()
