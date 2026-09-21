"""Отчёты по клиенту, банку и рискам: текст, JSON, CSV и графики."""

import csv
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

from transaction import TransactionStatus, filter_client_transactions

matplotlib.use("Agg")


class ReportType:
    """Типы отчётов."""

    CLIENT = "client"
    BANK = "bank"
    RISK = "risk"


class ReportBuilder:
    """Строит отчёты в едином формате и экспортирует их.

    Каждый отчёт — словарь с ключами report_type, generated_at,
    summary (сводные показатели) и rows (табличные строки).
    Единая структура позволяет использовать одни и те же функции
    экспорта для всех типов отчётов.
    """

    def __init__(self, bank, transactions: list | None = None):
        self.bank = bank
        self.transactions = transactions if transactions is not None else []

    def build_client_report(self, client_id: str) -> dict:
        client = self.bank.get_client(client_id)
        accounts = [account.get_account_info() for account in self.bank.get_client_accounts(client_id)]

        balance_by_currency: dict = {}
        for info in accounts:
            balance_by_currency[info["currency"]] = (
                balance_by_currency.get(info["currency"], 0) + info["balance"]
            )

        rows = [
            {
                "transaction_id": t.transaction_id,
                "type": t.transaction_type,
                "amount": t.amount,
                "fee": t.fee,
                "sender_account_id": t.sender_account_id,
                "receiver_account_id": t.receiver_account_id,
                "status": t.status,
            }
            for t in filter_client_transactions(self.transactions, self.bank, client_id)
        ]

        return self._make_report(ReportType.CLIENT, {
            "client_id": client_id,
            "full_name": client.full_name,
            "status": client.status,
            "accounts": accounts,
            "balance_by_currency": balance_by_currency,
            "risk_profile": self.bank.get_client_risk_profile(client_id),
        }, rows)

    def build_bank_report(self, currency: str = "RUB") -> dict:
        rows = [
            {"client_id": client.client_id, "full_name": client.full_name, "balance": total}
            for client, total in self.bank.get_clients_ranking(currency=currency)
        ]

        statistics = None
        if self.transactions:
            statistics = {
                "total": len(self.transactions),
                "completed": self._count_status(TransactionStatus.COMPLETED),
                "failed": self._count_status(TransactionStatus.FAILED),
            }

        return self._make_report(ReportType.BANK, {
            "bank_name": self.bank.name,
            "ranking_currency": currency,
            "num_clients": len(self.bank.clients),
            "num_accounts": len(self.bank.accounts),
            "total_balance_by_currency": self.bank.get_total_balance(),
            "transaction_statistics": statistics,
        }, rows)

    def build_risk_report(self) -> dict:
        events = self.bank.get_suspicious_operations_report()
        rows = [
            {
                "event_id": event.event_id,
                "timestamp": event.timestamp.isoformat(),
                "severity": event.severity,
                "category": event.category,
                "client_id": event.client_id,
                "message": event.message,
            }
            for event in events
        ]
        by_severity: dict[str, int] = {}
        for event in events:
            by_severity[event.severity] = by_severity.get(event.severity, 0) + 1

        return self._make_report(ReportType.RISK, {
            "total_events": len(events),
            "by_severity": by_severity,
        }, rows)

    def _make_report(self, report_type: str, summary: dict, rows: list[dict]) -> dict:
        return {
            "report_type": report_type,
            "generated_at": self.bank.now().isoformat(timespec="seconds"),
            "summary": summary,
            "rows": rows,
        }

    def _count_status(self, status: str) -> int:
        return sum(1 for t in self.transactions if t.status == status)

    @staticmethod
    def to_text(report: dict) -> str:
        lines = [
            f"=== Отчёт: {report['report_type']} ===",
            f"Сформирован: {report['generated_at']}",
            "",
            "-- Сводка --",
        ]
        for key, value in report["summary"].items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            lines.append(f"{key}: {value}")
        lines += ["", f"-- Детали ({len(report['rows'])} строк) --"]
        lines += [json.dumps(row, ensure_ascii=False, default=str) for row in report["rows"]]
        return "\n".join(lines)

    @staticmethod
    def export_to_json(report: dict, filepath) -> Path:
        """Сохраняет отчёт в JSON; default=str сериализует Decimal и datetime."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2, default=str)
        return path

    @staticmethod
    def export_to_csv(report: dict, filepath) -> Path:
        """Сохраняет строки отчёта в CSV.

        Набор колонок собирается из всех строк в порядке первого появления
        ключа, поэтому строки с разным набором полей не ломают запись.
        newline="" обязателен для модуля csv, иначе в Windows появляются
        пустые строки между записями.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = report["rows"]
        fieldnames = list(dict.fromkeys(key for row in rows for key in row))
        with path.open("w", encoding="utf-8", newline="") as file:
            if fieldnames:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        return path

    def save_charts(self, report: dict, output_dir="reports_output/charts") -> list[Path]:
        """Строит графики для отчёта и возвращает пути к сохранённым файлам."""
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        builders = {
            ReportType.BANK: self._bank_charts,
            ReportType.RISK: self._risk_charts,
            ReportType.CLIENT: self._client_charts,
        }
        return builders[report["report_type"]](report, directory)

    def _bank_charts(self, report: dict, directory: Path) -> list[Path]:
        saved = []
        balance = report["summary"]["total_balance_by_currency"]
        positive = {currency: value for currency, value in balance.items() if value > 0}
        if positive:
            saved.append(self._save_pie_chart(
                positive, "Баланс банка по валютам", directory / "bank_balance_by_currency_pie.png",
            ))
        top_rows = report["rows"][:10]
        if top_rows:
            currency = report["summary"]["ranking_currency"]
            saved.append(self._save_bar_chart(
                {row["full_name"]: row["balance"] for row in top_rows},
                f"Баланс клиентов в пересчёте на {currency}", "Клиент", "Баланс",
                directory / "bank_clients_balance_bar.png",
            ))
        return saved

    def _risk_charts(self, report: dict, directory: Path) -> list[Path]:
        saved = []
        by_severity = report["summary"]["by_severity"]
        if by_severity:
            saved.append(self._save_pie_chart(
                by_severity, "Подозрительные события по важности", directory / "risk_severity_pie.png",
            ))
        by_client: dict[str, int] = {}
        for row in report["rows"]:
            key = row["client_id"] or "—"
            by_client[key] = by_client.get(key, 0) + 1
        if by_client:
            saved.append(self._save_bar_chart(
                by_client, "Подозрительные события по клиентам", "Клиент", "Количество",
                directory / "risk_by_client_bar.png",
            ))
        return saved

    def _client_charts(self, report: dict, directory: Path) -> list[Path]:
        saved = []
        client_id = report["summary"]["client_id"]
        by_type: dict[str, int] = {}
        for row in report["rows"]:
            by_type[row["type"]] = by_type.get(row["type"], 0) + 1
        if by_type:
            saved.append(self._save_bar_chart(
                by_type, "Операции клиента по типам", "Тип", "Количество",
                directory / f"client_{client_id}_types_bar.png",
            ))
        accounts = report["summary"]["accounts"]
        if accounts:
            timeline = self.build_balance_movement(accounts[0]["account_id"])
            if timeline:
                saved.append(self._save_line_chart(
                    timeline, "Движение баланса счёта", "Операция №", "Накопленное изменение",
                    directory / f"client_{client_id}_balance_line.png",
                ))
        return saved

    def build_balance_movement(self, account_id: str) -> list[float]:
        """Накопленное изменение баланса счёта по успешным транзакциям.

        Отсчёт идёт от нуля, поэтому ряд показывает тренд, а не
        абсолютный баланс: начальные пополнения в обход обработчика
        транзакций в него не входят. Зачисление при переводе между
        валютами учитывается в валюте отправителя.
        """
        movement = 0.0
        timeline = []
        for transaction in self.transactions:
            if transaction.status != TransactionStatus.COMPLETED:
                continue
            changed = False
            if transaction.receiver_account_id == account_id:
                movement += float(transaction.amount)
                changed = True
            if transaction.sender_account_id == account_id:
                movement -= float(transaction.amount + transaction.fee)
                changed = True
            if changed:
                timeline.append(movement)
        return timeline

    @staticmethod
    def _save_pie_chart(data: dict, title: str, path: Path) -> Path:
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.pie([float(value) for value in data.values()], labels=list(data), autopct="%1.1f%%")
        ax.set_title(title)
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        return path

    @staticmethod
    def _save_bar_chart(data: dict, title: str, xlabel: str, ylabel: str, path: Path) -> Path:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.bar(list(data), [float(value) for value in data.values()])
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", labelrotation=30)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path

    @staticmethod
    def _save_line_chart(values: list[float], title: str, xlabel: str, ylabel: str, path: Path) -> Path:
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.plot(range(1, len(values) + 1), values, marker="o")
        ax.axhline(0, linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path