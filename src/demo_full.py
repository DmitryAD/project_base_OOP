"""Сквозная демонстрация возможностей PyBank."""

import logging
from datetime import date, datetime
from pathlib import Path

from bank import Bank
from client import Client
from exceptions import AccountFrozenError, AuthenticationError, SuspiciousOperationBlockedError
from main import BankAccount, InvestmentAccount, PremiumAccount, SavingsAccount
from reports import ReportBuilder
from simulation import BankSimulation
from transaction import Transaction, TransactionProcessor, TransactionQueue, TransactionType

DAYTIME = datetime(2026, 1, 1, 12, 0)
REPORTS_DIR = Path("reports_output")


def format_amounts(amounts: dict) -> str:
    return ", ".join(f"{key}: {value}" for key, value in amounts.items())


def print_header(title: str):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_accounts():
    print_header("Счета и их типы")

    account = BankAccount(owner="Иван Иванов", currency="RUB")
    account.deposit(1000)
    account.withdraw(300)
    print(account)

    account.freeze()
    try:
        account.deposit(100)
    except AccountFrozenError as error:
        print(f"Операция по замороженному счёту отклонена: {error}")
    account.unfreeze()

    savings = SavingsAccount(owner="Анна Смирнова", currency="RUB", min_balance=1000, monthly_rate=0.03)
    savings.deposit(5000)
    print(f"Начислены проценты: {savings.apply_monthly_interest()}")
    print(savings)

    premium = PremiumAccount(owner="Олег Кузнецов", currency="USD", overdraft_limit=1000, withdrawal_fee=10)
    premium.deposit(200)
    premium.withdraw(500)
    print(premium)

    investment = InvestmentAccount(owner="Мария Петрова", currency="RUB")
    investment.deposit(10000)
    investment.buy_asset("stocks", 4000)
    print(investment)
    print(f"Прогноз портфеля через год: {format_amounts(investment.project_yearly_growth())}")


def demo_bank(bank: Bank) -> dict:
    print_header("Банк, клиенты и аутентификация")

    alice = bank.add_client(Client(
        full_name="Алина Волкова", birth_date=date(1995, 6, 20),
        password="qwerty", phone="+79990000001", email="alina@example.com",
    ))
    bob = bank.add_client(Client(full_name="Борис Николаев", birth_date=date(1988, 3, 15), password="secret"))
    print(f"Клиенты: {alice.full_name}, {bob.full_name}")

    accounts = {
        "alice_rub": bank.open_account(alice.client_id, account_type="bank", currency="RUB"),
        "alice_usd": bank.open_account(alice.client_id, account_type="premium", currency="USD", overdraft_limit=500),
        "bob_rub": bank.open_account(bob.client_id, account_type="bank", currency="RUB"),
    }
    bank.deposit_to_account(accounts["alice_rub"].account_id, 50000)
    bank.deposit_to_account(accounts["alice_usd"].account_id, 1000)
    bank.deposit_to_account(accounts["bob_rub"].account_id, 5000)
    print(f"Общий баланс банка: {format_amounts(bank.get_total_balance())}")

    try:
        bank.authenticate_client(alice.client_id, "wrong-password")
    except AuthenticationError as error:
        print(f"Вход с неверным паролем: {error}")
    print(f"Вход с верным паролем: {bank.authenticate_client(alice.client_id, 'qwerty')}")

    print("Рейтинг клиентов (все счета в пересчёте на RUB):")
    for client, total in bank.get_clients_ranking():
        print(f"  {client.full_name}: {total}")

    return {"alice": alice, "bob": bob, **accounts}


def demo_transactions(bank: Bank, context: dict) -> TransactionProcessor:
    print_header("Очередь и обработка транзакций")

    alice_rub = context["alice_rub"].account_id
    alice_usd = context["alice_usd"].account_id
    bob_rub = context["bob_rub"].account_id

    queue = TransactionQueue()
    for transaction in (
        Transaction(TransactionType.DEPOSIT, 1000, receiver_account_id=alice_rub, priority=1),
        Transaction(TransactionType.WITHDRAWAL, 200, sender_account_id=bob_rub, priority=1),
        Transaction(TransactionType.INTERNAL_TRANSFER, 2000, sender_account_id=alice_rub, receiver_account_id=bob_rub, priority=5),
        Transaction(TransactionType.EXTERNAL_TRANSFER, 3000, sender_account_id=alice_rub, receiver_account_id=bob_rub, priority=3),
        Transaction(TransactionType.INTERNAL_TRANSFER, 300, sender_account_id=alice_usd, receiver_account_id=bob_rub, priority=4),
        Transaction(TransactionType.DEPOSIT, 500, receiver_account_id=bob_rub, priority=10),
    ):
        queue.add(transaction)

    processor = TransactionProcessor(bank)
    print(f"В очереди {len(queue)} транзакций, обработка по приоритету:")
    while (transaction := queue.get_next()) is not None:
        processor.process(transaction)
        print(f"  {transaction}")
    print(f"Ошибок обработки: {len(processor.error_log)}")
    return processor


def demo_risk(bank: Bank, context: dict, processor: TransactionProcessor):
    print_header("Аудит и анализ рисков")

    bank.withdraw_from_account(context["alice_rub"].account_id, context["alice"].client_id, 100)
    print("Обычное снятие выполнено без блокировки")

    risky_bank = Bank(name="RiskBank", time_provider=lambda: DAYTIME)
    client = risky_bank.add_client(Client(
        full_name="Павел Орлов", birth_date=date(1990, 1, 1), password="risk-demo",
    ))
    account = risky_bank.open_account(client.client_id, max_transaction_limit=2_000_000)
    risky_bank.deposit_to_account(account.account_id, 1_000_000)

    for _ in range(5):
        risky_bank.withdraw_from_account(account.account_id, client.client_id, 100)
    try:
        risky_bank.withdraw_from_account(account.account_id, client.client_id, 600_000)
    except SuspiciousOperationBlockedError as error:
        print(f"Заблокировано: {error}")

    print(f"Подозрительных событий: {len(risky_bank.get_suspicious_operations_report())}")
    print(f"Риск-профиль клиента: {risky_bank.get_client_risk_profile(client.client_id)}")
    print(f"Статистика ошибок обработки: {bank.get_error_statistics(processor.error_log)}")


def demo_simulation() -> BankSimulation:
    print_header("Симуляция нагрузки")

    simulation = BankSimulation(
        num_clients=8, num_accounts=12, num_transactions=40, seed=42,
        time_provider=lambda: DAYTIME,
    ).run()

    client = simulation.get_most_active_client()
    print(f"\nСчета клиента {client.full_name}:")
    for account in simulation.get_client_accounts(client.client_id):
        print(f"  {account}")

    history = simulation.get_client_transaction_history(client.client_id)
    print(f"История операций ({len(history)}):")
    for transaction in history:
        print(f"  {transaction}")
    print(f"Риск-профиль: {simulation.get_client_risk_profile(client.client_id)}")

    print("\nТоп-3 клиентов по балансу (все счета в пересчёте на RUB):")
    for top_client, total in simulation.get_top_clients(3):
        print(f"  {top_client.full_name}: {total}")
    print(f"Статистика транзакций: {simulation.get_transaction_statistics()}")
    print(f"Общий баланс банка: {format_amounts(simulation.get_total_balance())}")
    return simulation


def demo_reports(simulation: BankSimulation):
    print_header("Отчёты и графики")

    builder = ReportBuilder(simulation.bank, transactions=simulation.transactions)
    client = simulation.get_most_active_client()
    reports = {
        "client": builder.build_client_report(client.client_id),
        "bank": builder.build_bank_report(),
        "risk": builder.build_risk_report(),
    }

    saved_files = []
    for name, report in reports.items():
        print(f"\n{builder.to_text(report)}")
        saved_files.append(builder.export_to_json(report, REPORTS_DIR / f"{name}_report.json"))
        saved_files.append(builder.export_to_csv(report, REPORTS_DIR / f"{name}_report.csv"))
        saved_files += builder.save_charts(report, REPORTS_DIR / "charts")

    print(f"\nСохранено файлов: {len(saved_files)} в каталоге {REPORTS_DIR}/")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    demo_accounts()
    bank = Bank(name="PyBank", time_provider=lambda: DAYTIME)
    context = demo_bank(bank)
    processor = demo_transactions(bank, context)
    demo_risk(bank, context, processor)
    simulation = demo_simulation()
    demo_reports(simulation)


if __name__ == "__main__":
    main()