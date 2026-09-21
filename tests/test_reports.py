import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bank import Bank
from client import Client
from reports import ReportBuilder, ReportType
from transaction import Transaction, TransactionProcessor, TransactionQueue, TransactionType

Client.PBKDF2_ITERATIONS = 1_000

DAYTIME = datetime(2026, 1, 1, 12, 0)


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


def make_bank_with_history():
    bank = make_bank(name="ReportTestBank")
    alice = make_client(bank, "Алина Волкова")
    bob = make_client(bank, "Борис Николаев")
    alice_account = open_funded_account(bank, alice, 10000)
    bob_account = open_funded_account(bank, bob)

    queue = TransactionQueue()
    queue.add(Transaction(
        TransactionType.INTERNAL_TRANSFER, 500,
        sender_account_id=alice_account.account_id,
        receiver_account_id=bob_account.account_id,
    ))
    queue.add(Transaction(
        TransactionType.WITHDRAWAL, 50000,
        sender_account_id=alice_account.account_id,
    ))

    processor = TransactionProcessor(bank)
    transactions = []
    while (transaction := queue.get_next()) is not None:
        processor.process(transaction)
        transactions.append(transaction)
    return bank, alice, bob, transactions


class ReportTestCase(unittest.TestCase):

    def setUp(self):
        self.bank, self.alice, self.bob, transactions = make_bank_with_history()
        self.builder = ReportBuilder(self.bank, transactions=transactions)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.output = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()


class TestReportBuilderReportTypes(ReportTestCase):

    def test_client_report(self):
        report = self.builder.build_client_report(self.alice.client_id)
        self.assertEqual(report["report_type"], ReportType.CLIENT)
        self.assertEqual(report["summary"]["client_id"], self.alice.client_id)
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(report["summary"]["balance_by_currency"], {"RUB": 9500})

    def test_bank_report(self):
        report = self.builder.build_bank_report()
        self.assertEqual(report["report_type"], ReportType.BANK)
        self.assertEqual(len(report["rows"]), 2)
        self.assertEqual(report["summary"]["transaction_statistics"], {"total": 2, "completed": 1, "failed": 1})

    def test_risk_report(self):
        report = self.builder.build_risk_report()
        self.assertEqual(report["report_type"], ReportType.RISK)
        self.assertEqual(report["summary"]["total_events"], len(report["rows"]))

    def test_report_without_transactions(self):
        report = ReportBuilder(self.bank).build_client_report(self.alice.client_id)
        self.assertEqual(report["rows"], [])

    def test_to_text_contains_key_data(self):
        report = self.builder.build_client_report(self.alice.client_id)
        text = self.builder.to_text(report)
        self.assertIn(report["report_type"], text)
        self.assertIn(self.alice.client_id, text)


class TestReportBuilderExports(ReportTestCase):

    def test_export_to_json(self):
        report = self.builder.build_client_report(self.alice.client_id)
        path = self.builder.export_to_json(report, self.output / "nested" / "client.json")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["report_type"], ReportType.CLIENT)
        self.assertEqual(loaded["rows"][0]["amount"], "500")

    def test_export_to_csv(self):
        report = self.builder.build_bank_report()
        path = self.builder.export_to_csv(report, self.output / "bank.csv")
        with path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["full_name"], "Алина Волкова")

    def test_export_empty_report_to_csv(self):
        report = ReportBuilder(self.bank).build_client_report(self.bob.client_id)
        path = self.builder.export_to_csv(report, self.output / "empty.csv")
        self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_save_charts_for_every_report_type(self):
        reports = [
            self.builder.build_client_report(self.alice.client_id),
            self.builder.build_bank_report(),
            self.builder.build_risk_report(),
        ]
        for report in reports:
            with self.subTest(report_type=report["report_type"]):
                saved = self.builder.save_charts(report, self.output)
                self.assertGreater(len(saved), 0)
                self.assertTrue(all(path.exists() for path in saved))

    def test_balance_movement_uses_completed_transactions_only(self):
        account_id = self.alice.account_ids[0]
        self.assertEqual(self.builder.build_balance_movement(account_id), [-500.0])


if __name__ == "__main__":
    unittest.main()
