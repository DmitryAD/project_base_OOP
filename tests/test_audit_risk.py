import sys
import os
import unittest
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bank import Bank
from client import Client
from audit import AuditLog, AuditSeverity
from risk import RiskAnalyzer, RiskLevel
from exceptions import SuspiciousOperationBlockedError


def make_bank(time_provider=datetime.now):
    return Bank(name="TestBank", time_provider=time_provider)


def make_client(bank, name="Тест"):
    return bank.add_client(Client(full_name=name, birth_date=date(1990, 1, 1), password="pass"))


class TestAuditLog(unittest.TestCase):

    def test_record_stores_event_in_memory(self):
        log = AuditLog()
        log.record(AuditSeverity.INFO, "test", "сообщение")
        self.assertEqual(len(log), 1)

    def test_filter_by_severity(self):
        log = AuditLog()
        log.record(AuditSeverity.INFO, "test", "обычное")
        log.record(AuditSeverity.CRITICAL, "test", "опасное")
        critical_events = log.filter(severity=AuditSeverity.CRITICAL)
        self.assertEqual(len(critical_events), 1)
        self.assertEqual(critical_events[0].message, "опасное")

    def test_filter_by_client_id(self):
        log = AuditLog()
        log.record(AuditSeverity.INFO, "test", "событие А", client_id="c1")
        log.record(AuditSeverity.INFO, "test", "событие Б", client_id="c2")
        self.assertEqual(len(log.filter(client_id="c1")), 1)


class TestRiskAnalyzer(unittest.TestCase):

    def test_normal_operation_is_low_risk(self):
        analyzer = RiskAnalyzer(time_provider=lambda: datetime(2026, 1, 1, 12, 0))
        level, reasons = analyzer.analyze(amount=1000, recent_operation_timestamps=[], is_new_receiver=False)
        self.assertEqual(level, RiskLevel.LOW)
        self.assertEqual(reasons, [])

    def test_large_amount_alone_is_medium_risk(self):
        analyzer = RiskAnalyzer(time_provider=lambda: datetime(2026, 1, 1, 12, 0))
        level, reasons = analyzer.analyze(amount=600000, recent_operation_timestamps=[], is_new_receiver=False)
        self.assertEqual(level, RiskLevel.MEDIUM)

    def test_large_amount_at_night_is_high_risk(self):
        # два признака сразу: крупная сумма + ночное время
        analyzer = RiskAnalyzer(time_provider=lambda: datetime(2026, 1, 1, 2, 0))
        level, reasons = analyzer.analyze(amount=600000, recent_operation_timestamps=[], is_new_receiver=False)
        self.assertEqual(level, RiskLevel.HIGH)
        self.assertEqual(len(reasons), 2)

    def test_frequent_operations_detected(self):
        now = datetime(2026, 1, 1, 12, 0)
        analyzer = RiskAnalyzer(time_provider=lambda: now)
        recent = [now - timedelta(minutes=1) for _ in range(5)]
        level, reasons = analyzer.analyze(amount=100, recent_operation_timestamps=recent, is_new_receiver=False)
        self.assertEqual(level, RiskLevel.MEDIUM)
        self.assertIn("частые операции", reasons[0])

    def test_new_receiver_detected(self):
        analyzer = RiskAnalyzer(time_provider=lambda: datetime(2026, 1, 1, 12, 0))
        level, reasons = analyzer.analyze(amount=100, recent_operation_timestamps=[], is_new_receiver=True)
        self.assertEqual(level, RiskLevel.MEDIUM)


class TestBankRiskIntegration(unittest.TestCase):

    def test_normal_withdrawal_is_not_blocked(self):
        bank = make_bank(time_provider=lambda: datetime(2026, 1, 1, 12, 0))
        client = make_client(bank)
        account = bank.open_account(client.client_id, currency="RUB")
        bank.deposit_to_account(account.get_account_info()["account_id"], 5000)

        result = bank.withdraw_from_account(account.get_account_info()["account_id"], client.client_id, 1000)
        self.assertEqual(result, 4000)

    def test_high_risk_withdrawal_is_blocked(self):
        # ночь (2:00) + крупная сумма = два признака = HIGH => блокировка
        bank = make_bank(time_provider=lambda: datetime(2026, 1, 1, 2, 0))
        client = make_client(bank)
        account = bank.open_account(client.client_id, currency="RUB")
        bank.deposit_to_account(account.get_account_info()["account_id"], 1_000_000)

        with self.assertRaises(SuspiciousOperationBlockedError):
            bank.withdraw_from_account(account.get_account_info()["account_id"], client.client_id, 600000)

        # деньги не должны были списаться
        self.assertEqual(account.get_account_info()["balance"], 1_000_000)

    def test_blocked_operation_is_logged_as_critical(self):
        bank = make_bank(time_provider=lambda: datetime(2026, 1, 1, 2, 0))
        client = make_client(bank)
        account = bank.open_account(client.client_id, currency="RUB")
        bank.deposit_to_account(account.get_account_info()["account_id"], 1_000_000)

        with self.assertRaises(SuspiciousOperationBlockedError):
            bank.withdraw_from_account(account.get_account_info()["account_id"], client.client_id, 600000)

        report = bank.get_suspicious_operations_report()
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0].severity, AuditSeverity.CRITICAL)

    def test_client_risk_profile_counts_by_level(self):
        bank = make_bank(time_provider=lambda: datetime(2026, 1, 1, 12, 0))
        client = make_client(bank)
        account = bank.open_account(client.client_id, currency="RUB")
        bank.deposit_to_account(account.get_account_info()["account_id"], 1_000_000)

        bank.withdraw_from_account(account.get_account_info()["account_id"], client.client_id, 100)  # low
        bank.withdraw_from_account(account.get_account_info()["account_id"], client.client_id, 600000)  # medium

        profile = bank.get_client_risk_profile(client.client_id)
        self.assertEqual(profile["low"], 1)
        self.assertEqual(profile["medium"], 1)
        self.assertEqual(profile["high"], 0)


if __name__ == "__main__":
    unittest.main()
