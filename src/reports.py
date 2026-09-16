"""
День 7: система отчётности и визуализации.

ReportBuilder строится ПОЛНОСТЬЮ поверх публичного API Bank (и,
опционально, transaction_log из BankSimulation Дня 6) — ни один
существующий файл не меняется.
"""

import csv
import json
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # headless-бэкенд: рисует прямо в файл, без окна.
# Важно для CI и Codespaces — там нет графического дисплея, и обычный
# бэкенд matplotlib попытался бы его найти и упал бы с ошибкой. "Agg" —
# бэкенд, который просто рендерит картинку в PNG-файл, ничего не показывая.
import matplotlib.pyplot as plt

from transaction import TransactionStatus


class ReportBuilder:
    """
    Строит отчёты трёх типов (по клиенту, по банку, по рискам) в виде
    единообразного dict {"report_type", "generated_at", "summary", "rows"},
    и умеет экспортировать их в текст, JSON, CSV и графики.
    """

    def __init__(self, bank, transaction_log: list = None):
        self.bank = bank
        # transaction_log — необязательный: без него отчёты по клиенту/риску
        # всё равно построятся (риск-профиль и подозрительные операции
        # хранятся внутри самого Bank, в audit_log), просто "rows" с историей
        # транзакций будут пустыми
        self.transaction_log = transaction_log if transaction_log is not None else []

    # ---------- построение отчётов ----------

    def build_client_report(self, client_id: str) -> dict:
        client = self.bank.clients[client_id]
        accounts_info = [self.bank.get_account(aid).get_account_info() for aid in client.account_ids]

        balance_by_currency = {}
        for info in accounts_info:
            balance_by_currency[info["currency"]] = balance_by_currency.get(info["currency"], 0.0) + info["balance"]

        history_rows = []
        for entry in self.transaction_log:
            t = entry["transaction"]
            sender_client = self.bank.get_client_id_for_account(t.sender_account_id) if t.sender_account_id else None
            receiver_client = self.bank.get_client_id_for_account(t.receiver_account_id) if t.receiver_account_id else None
            if client_id in (sender_client, receiver_client):
                history_rows.append({
                    "transaction_id": t.transaction_id,
                    "type": t.transaction_type,
                    "amount": t.amount,
                    "fee": t.fee,
                    "sender_account_id": t.sender_account_id,
                    "receiver_account_id": t.receiver_account_id,
                    "status": t.status,
                })

        return {
            "report_type": "client",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "client_id": client_id,
                "full_name": client.full_name,
                "status": client.status,
                "accounts": accounts_info,
                "balance_by_currency": balance_by_currency,
                "risk_profile": self.bank.get_client_risk_profile(client_id),
            },
            "rows": history_rows,
        }

    def build_bank_report(self) -> dict:
        ranking = self.bank.get_clients_ranking()
        rows = [
            {"client_id": client.client_id, "full_name": client.full_name, "balance": total}
            for client, total in ranking
        ]

        stats = None
        if self.transaction_log:
            total = len(self.transaction_log)
            completed = sum(1 for e in self.transaction_log if e["status"] == TransactionStatus.COMPLETED)
            failed = sum(1 for e in self.transaction_log if e["status"] == TransactionStatus.FAILED)
            stats = {"total": total, "completed": completed, "failed": failed}

        return {
            "report_type": "bank",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "bank_name": self.bank.name,
                "num_clients": len(self.bank.clients),
                "num_accounts": len(self.bank.accounts),
                "total_balance_by_currency": self.bank.get_total_balance(),
                "transaction_statistics": stats,
            },
            "rows": rows,
        }

    def build_risk_report(self) -> dict:
        events = self.bank.get_suspicious_operations_report()
        rows = [
            {
                "event_id": e.event_id,
                "timestamp": e.timestamp.isoformat(),
                "severity": e.severity,
                "client_id": e.client_id,
                "message": e.message,
            }
            for e in events
        ]

        by_severity = {}
        for e in events:
            by_severity[e.severity] = by_severity.get(e.severity, 0) + 1

        return {
            "report_type": "risk",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_events": len(events),
                "by_severity": by_severity,
            },
            "rows": rows,
        }

    # ---------- текстовый формат ----------

    def to_text(self, report: dict) -> str:
        lines = [f"=== Отчёт: {report['report_type']} ===", f"Сформирован: {report['generated_at']}", ""]
        lines.append("-- Сводка --")
        for key, value in report["summary"].items():
            lines.append(f"{key}: {value}")
        lines.append("")
        lines.append(f"-- Детали ({len(report['rows'])} строк) --")
        for row in report["rows"]:
            lines.append(str(row))
        return "\n".join(lines)

    # ---------- экспорт ----------

    def export_to_json(self, report: dict, filepath: str):
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        """
        default=str — подстраховка для json.dump: если в отчёте случайно
        останется значение, которое json не умеет сериализовать "из
        коробки" (например, объект datetime вместо уже готовой строки),
        json не упадёт с TypeError, а просто вызовет str() на нём.
        """
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    def export_to_csv(self, report: dict, filepath: str):
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        rows = report["rows"]
        if not rows:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("")
            return

        """
        dict.fromkeys-подобный трюк: собираем список ключей БЕЗ
        дубликатов, сохраняя порядок первого появления (обычные dict
        в Python 3.7+ гарантированно хранят порядок вставки). Так мы
        получаем полный набор колонок, даже если у разных строк отчёта
        чуть отличается набор ключей — иначе csv.DictWriter упал бы на
        строке с "лишним" или отсутствующим ключом.
        """
        fieldnames = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    fieldnames.append(key)
                    seen.add(key)

        # newline="" — без этого на Windows csv-модуль добавляет лишние
        # пустые строки между записями (особенность построчных концов
        # файла в разных ОС)
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    # ---------- графики ----------

    def _save_pie_chart(self, labels, values, title, filepath):
        plt.figure(figsize=(6, 6))
        plt.pie(values, labels=labels, autopct="%1.1f%%")
        plt.title(title)
        plt.savefig(filepath, bbox_inches="tight")
        plt.close()

    def _save_bar_chart(self, labels, values, title, xlabel, ylabel, filepath):
        plt.figure(figsize=(8, 5))
        plt.bar(labels, values)
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.xticks(rotation=30, ha="right")
        plt.tight_layout()
        plt.savefig(filepath)
        plt.close()

    def _save_line_chart(self, values, title, xlabel, ylabel, filepath):
        plt.figure(figsize=(8, 5))
        plt.plot(range(1, len(values) + 1), values, marker="o")
        plt.axhline(0, linewidth=0.8)
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        plt.tight_layout()
        plt.savefig(filepath)
        plt.close()

    def _build_balance_movement(self, account_id: str) -> list:
        """
        Строит временной ряд ДВИЖЕНИЯ баланса одного счёта — не
        абсолютное значение! Суммарное изменение от транзакций, начиная
        с условного нуля, в порядке их обработки. Это НЕ реальный баланс
        счёта (у которого мог быть ненулевой старт при открытии, минуя
        TransactionProcessor) — это график ТРЕНДА: растёт баланс или
        падает и насколько резко. Для точного текущего значения смотри
        account.get_account_info()["balance"].
        """
        movement = 0.0
        timeline = []
        for entry in self.transaction_log:
            t = entry["transaction"]
            if t.status != TransactionStatus.COMPLETED:
                continue
            changed = False
            if t.receiver_account_id == account_id:
                movement += t.amount
                changed = True
            if t.sender_account_id == account_id:
                movement -= (t.amount + t.fee)
                changed = True
            if changed:
                timeline.append(movement)
        return timeline

    def save_charts(self, report: dict, output_dir: str = "reports_output/charts") -> list:
        """
        Строит графики, подходящие конкретному типу отчёта, и сохраняет
        их в output_dir. Возвращает список путей к сохранённым файлам —
        удобно и для демонстрации, и для тестов (проверить, что файлы
        реально появились на диске).
        """
        os.makedirs(output_dir, exist_ok=True)
        saved_files = []
        report_type = report["report_type"]

        if report_type == "bank":
            balance = report["summary"]["total_balance_by_currency"]
            if balance:
                path = os.path.join(output_dir, "bank_balance_by_currency_pie.png")
                self._save_pie_chart(list(balance.keys()), list(balance.values()), "Баланс банка по валютам", path)
                saved_files.append(path)

            top_rows = report["rows"][:10]
            if top_rows:
                labels = [r["full_name"] for r in top_rows]
                values = [r["balance"] for r in top_rows]
                path = os.path.join(output_dir, "bank_clients_balance_bar.png")
                self._save_bar_chart(labels, values, "Баланс клиентов (RUB)", "Клиент", "Баланс", path)
                saved_files.append(path)

        elif report_type == "risk":
            by_severity = report["summary"]["by_severity"]
            if by_severity:
                path = os.path.join(output_dir, "risk_severity_pie.png")
                self._save_pie_chart(list(by_severity.keys()), list(by_severity.values()), "Подозрительные операции по важности", path)
                saved_files.append(path)

            by_client = {}
            for row in report["rows"]:
                by_client[row["client_id"]] = by_client.get(row["client_id"], 0) + 1
            if by_client:
                path = os.path.join(output_dir, "risk_by_client_bar.png")
                self._save_bar_chart(list(by_client.keys()), list(by_client.values()), "Подозрительные операции по клиентам", "Клиент", "Количество", path)
                saved_files.append(path)

        elif report_type == "client":
            by_type = {}
            for row in report["rows"]:
                by_type[row["type"]] = by_type.get(row["type"], 0) + 1
            if by_type:
                path = os.path.join(output_dir, f"client_{report['summary']['client_id']}_types_bar.png")
                self._save_bar_chart(list(by_type.keys()), list(by_type.values()), "Операции клиента по типам", "Тип", "Количество", path)
                saved_files.append(path)

            accounts = report["summary"]["accounts"]
            if accounts:
                account_id = accounts[0]["account_id"]
                timeline = self._build_balance_movement(account_id)
                if timeline:
                    path = os.path.join(output_dir, f"client_{report['summary']['client_id']}_balance_line.png")
                    self._save_line_chart(timeline, "Движение баланса счёта", "Операция №", "Накопленное изменение", path)
                    saved_files.append(path)

        return saved_files


def run_day_7_demo():
    from simulation import BankSimulation

    print("=" * 60)
    print("ДЕНЬ 7: Отчётность и визуализация")
    print("=" * 60)

    sim = BankSimulation(num_clients=8, num_accounts=12, num_transactions=40, seed=42)
    sim.generate_clients()
    sim.generate_accounts()
    sim.run_transactions()

    builder = ReportBuilder(sim.bank, transaction_log=sim.transaction_log)
    sample_client = max(sim.clients, key=lambda c: len(sim.get_client_transaction_history(c.client_id)))

    client_report = builder.build_client_report(sample_client.client_id)
    bank_report = builder.build_bank_report()
    risk_report = builder.build_risk_report()

    print("\n" + builder.to_text(client_report))
    print("\n" + builder.to_text(bank_report))
    print("\n" + builder.to_text(risk_report))

    output_dir = "reports_output"
    builder.export_to_json(client_report, os.path.join(output_dir, "client_report.json"))
    builder.export_to_csv(client_report, os.path.join(output_dir, "client_report.csv"))
    builder.export_to_json(bank_report, os.path.join(output_dir, "bank_report.json"))
    builder.export_to_csv(bank_report, os.path.join(output_dir, "bank_report.csv"))
    builder.export_to_json(risk_report, os.path.join(output_dir, "risk_report.json"))
    builder.export_to_csv(risk_report, os.path.join(output_dir, "risk_report.csv"))

    chart_dir = os.path.join(output_dir, "charts")
    saved_charts = []
    saved_charts += builder.save_charts(client_report, chart_dir)
    saved_charts += builder.save_charts(bank_report, chart_dir)
    saved_charts += builder.save_charts(risk_report, chart_dir)

    print(f"\nОтчёты сохранены в: {output_dir}/")
    print(f"Графики сохранены: {saved_charts}")


if __name__ == "__main__":
    run_day_7_demo()
