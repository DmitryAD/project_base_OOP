import sys
import os
import json
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bank import Bank
from client import Client
from transaction import Transaction, TransactionType, TransactionQueue, TransactionProcessor
from reports import ReportBuilder


def make_bank_with_history():
    bank = Bank(name="ReportTestBank")
    processor = TransactionProcessor(bank)

    alice = bank.add_client(Client(full_name="Алина Волкова", birth_date=date(1990, 1, 1), password="pass"))
    bob = bank.add_client(Client(full_name="Борис Николаев", birth_date=date(1988, 1, 1), password="pass"))

    alice_acc = bank.open_account(alice.client_id, currency="RUB")
    bob_acc = bank.open_account(bob.client_id, currency="RUB")
    bank.deposit_to_account(alice_acc.get_account_info()["account_id"], 10000)

    queue = TransactionQueue()
    queue.add(Transaction(
        TransactionType.INTERNAL_TRANSFER, 500,
        sender_account_id=alice_acc.get_account_info()["account_id"],
        receiver_account_id=bob_acc.get_account_info()["account_id"],
    ))
    queue.add(Transaction(
        TransactionType.WITHDRAWAL, 50000,
        sender_account_id=alice_acc.get_account_info()["account_id"],
    ))  # заведомо упадёт — не хватит средств после перевода выше

    transaction_log = []
    while True:
        t = queue.get_next()
        if t is None:
            break
        processor.process(t)
        transaction_log.append({"transaction": t, "status": t.status})

    return bank, alice, bob, transaction_log


class TestReportBuilderReportTypes(unittest.TestCase):

    def test_build_client_report_structure(self):
        bank, alice, bob, log = make_bank_with_history()
        builder = ReportBuilder(bank, transaction_log=log)
        report = builder.build_client_report(alice.client_id)

        self.assertEqual(report["report_type"], "client")
        self.assertEqual(report["summary"]["client_id"], alice.client_id)
        self.assertGreaterEqual(len(report["rows"]), 1)

    def test_build_bank_report_contains_all_clients(self):
        bank, alice, bob, log = make_bank_with_history()
        builder = ReportBuilder(bank, transaction_log=log)
        report = builder.build_bank_report()

        self.assertEqual(report["report_type"], "bank")
        self.assertEqual(len(report["rows"]), 2)

    def test_build_risk_report_structure(self):
        bank, alice, bob, log = make_bank_with_history()
        builder = ReportBuilder(bank, transaction_log=log)
        report = builder.build_risk_report()

        self.assertEqual(report["report_type"], "risk")
        self.assertIn("total_events", report["summary"])


class TestReportBuilderExports(unittest.TestCase):

    def test_export_to_json_creates_readable_file(self):
        bank, alice, bob, log = make_bank_with_history()
        builder = ReportBuilder(bank, transaction_log=log)
        report = builder.build_bank_report()

        with tempfile.TemporaryDirectory() as tmp_dir:
            filepath = os.path.join(tmp_dir, "bank_report.json")
            builder.export_to_json(report, filepath)

            with open(filepath, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded["report_type"], "bank")

    def test_export_to_csv_creates_file_with_header(self):
        bank, alice, bob, log = make_bank_with_history()
        builder = ReportBuilder(bank, transaction_log=log)
        report = builder.build_bank_report()

        with tempfile.TemporaryDirectory() as tmp_dir:
            filepath = os.path.join(tmp_dir, "bank_report.csv")
            builder.export_to_csv(report, filepath)

            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("full_name", content)

    def test_save_charts_creates_png_files(self):
        bank, alice, bob, log = make_bank_with_history()
        builder = ReportBuilder(bank, transaction_log=log)
        report = builder.build_bank_report()

        with tempfile.TemporaryDirectory() as tmp_dir:
            saved = builder.save_charts(report, output_dir=tmp_dir)
            self.assertGreater(len(saved), 0)
            for path in saved:
                self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
