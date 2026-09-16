"""
Сквозная демонстрация всего проекта: последовательно проходит по
функциональности, реализованной за Дни 1-5. Каждый следующий день
использует объекты (банк, клиентов, счета), созданные на предыдущих —
это показывает, что слои системы работают ВМЕСТЕ, а не только
по отдельности в своих собственных demo().
"""

from datetime import date, datetime

from main import BankAccount, SavingsAccount, PremiumAccount, InvestmentAccount
from exceptions import AccountFrozenError, SuspiciousOperationBlockedError
from client import Client
from bank import Bank
from transaction import Transaction, TransactionType, TransactionQueue, TransactionProcessor


class _TimeSwitch:
    """
    Вспомогательный класс-переключатель времени для демонстрации.

    Обычная lambda всегда возвращает одно и то же значение, а в demo_day_5
    нам нужно, чтобы ОДИН И ТОТ ЖЕ banks сначала "прожил" днём (чтобы
    пополнение счёта прошло без ночной блокировки), а потом переключился
    на ночь (чтобы проверить блокировку по риску). Поэтому вместо функции
    используем объект с состоянием: метод __call__ делает экземпляр класса
    вызываемым, как функцию (Bank ожидает именно вызываемый time_provider —
    ему всё равно, function это, lambda или объект с __call__, лишь бы
    можно было написать time_provider() и получить datetime).
    """
    def __init__(self, initial):
        self.current = initial

    def __call__(self):
        return self.current


def demo_day_1_2():
    """Дни 1-2: базовый счёт и три его подтипа с полиморфным поведением."""
    print("\n" + "=" * 60)
    print("ДЕНЬ 1-2: Базовые счета и их подтипы")
    print("=" * 60)

    acc = BankAccount(owner="Иван Иванов", currency="RUB")
    acc.deposit(1000)
    acc.withdraw(300)
    print(acc)

    acc.freeze()
    try:
        acc.deposit(100)
    except AccountFrozenError as e:
        print(f"Операция над замороженным счётом отклонена (ожидаемо): {e}")
    acc.unfreeze()

    savings = SavingsAccount(owner="Анна Смирнова", currency="RUB", min_balance=1000, monthly_rate=0.03)
    savings.deposit(5000)
    print(f"Начислены проценты по накопительному счёту: {savings.apply_monthly_interest():.2f}")
    print(savings)

    premium = PremiumAccount(owner="Олег Кузнецов", currency="USD", overdraft_limit=1000, withdrawal_fee=10)
    premium.deposit(200)
    premium.withdraw(500)  # уйдёт в минус за счёт овердрафта — разрешено для Premium
    print(premium)

    invest = InvestmentAccount(owner="Мария Петрова", currency="RUB")
    invest.deposit(10000)
    invest.buy_asset("stocks", 4000)
    print(invest)
    print(f"Прогноз роста портфеля через год: {invest.project_yearly_growth()}")


def demo_day_3(bank: Bank):
    """День 3: клиенты, счета через Bank, аутентификация, статистика."""
    print("\n" + "=" * 60)
    print("ДЕНЬ 3: Bank, клиенты, аутентификация")
    print("=" * 60)

    alice = bank.add_client(Client(
        full_name="Алина Волкова", birth_date=date(1995, 6, 20),
        phone="+79990000001", email="alina@example.com", password="qwerty",
    ))
    bob = bank.add_client(Client(full_name="Борис Николаев", birth_date=date(1988, 3, 15), password="secret"))
    print(f"Добавлены клиенты: {alice.full_name}, {bob.full_name}")

    alice_acc = bank.open_account(alice.client_id, account_type="bank", currency="RUB")
    alice_usd_acc = bank.open_account(alice.client_id, account_type="premium", currency="USD", overdraft_limit=500)
    bob_acc = bank.open_account(bob.client_id, account_type="bank", currency="RUB")

    bank.deposit_to_account(alice_acc.get_account_info()["account_id"], 50000)
    bank.deposit_to_account(alice_usd_acc.get_account_info()["account_id"], 1000)
    bank.deposit_to_account(bob_acc.get_account_info()["account_id"], 5000)
    print(f"Счета открыты и пополнены. Общий баланс банка по валютам: {bank.get_total_balance()}")

    print("Попытка входа с неверным паролем:")
    try:
        bank.authenticate_client(alice.client_id, "wrong-password")
    except Exception as e:
        print(f"  Ошибка (ожидаемо): {e}")
    ok = bank.authenticate_client(alice.client_id, "qwerty")
    print(f"Вход с верным паролем: {ok}")

    ranking = bank.get_clients_ranking()
    print("Рейтинг клиентов по балансу (RUB):")
    for client, total in ranking:
        print(f"  {client.full_name}: {total:.2f}")

    return alice, bob, alice_acc, alice_usd_acc, bob_acc


def demo_day_4(bank: Bank, alice, bob, alice_acc, alice_usd_acc, bob_acc):
    """День 4: очередь транзакций с приоритетами и их обработка."""
    print("\n" + "=" * 60)
    print("ДЕНЬ 4: Очередь и обработка транзакций")
    print("=" * 60)

    processor = TransactionProcessor(bank)
    alice_id = alice_acc.get_account_info()["account_id"]
    alice_usd_id = alice_usd_acc.get_account_info()["account_id"]
    bob_id = bob_acc.get_account_info()["account_id"]

    # разные типы и приоритеты — чтобы показать, что очередь реально
    # обрабатывает их не в порядке добавления, а по приоритету (heapq)
    transactions = [
        Transaction(TransactionType.DEPOSIT, 1000, receiver_account_id=alice_id, priority=1),
        Transaction(TransactionType.WITHDRAWAL, 200, sender_account_id=bob_id, priority=1),
        Transaction(TransactionType.INTERNAL_TRANSFER, 2000, sender_account_id=alice_id, receiver_account_id=bob_id, priority=5),
        Transaction(TransactionType.EXTERNAL_TRANSFER, 3000, sender_account_id=alice_id, receiver_account_id=bob_id, priority=3),
        Transaction(TransactionType.INTERNAL_TRANSFER, 300, sender_account_id=alice_usd_id, receiver_account_id=bob_id, priority=4),
        Transaction(TransactionType.DEPOSIT, 500, receiver_account_id=bob_id, priority=10),  # высокий приоритет — почти первая в очереди
    ]

    queue = TransactionQueue()
    for t in transactions:
        queue.add(t)

    print(f"В очереди {len(queue)} транзакций. Обрабатываем по приоритету:")
    processed = 0
    while True:
        t = queue.get_next()
        if t is None:
            break
        processor.process(t)
        print(f"  {t}")
        processed += 1

    print(f"Обработано транзакций: {processed}. Ошибок в логе процессора: {len(processor.error_log)}")
    return processor


def demo_day_5(bank: Bank, alice, alice_acc, processor):
    """День 5: риск-анализ и аудит поверх операций."""
    print("\n" + "=" * 60)
    print("ДЕНЬ 5: Аудит и анализ рисков")
    print("=" * 60)

    print("Обычная небольшая операция (не должна блокироваться):")
    bank.withdraw_from_account(alice_acc.get_account_info()["account_id"], alice.client_id, 100)
    print("  прошло без блокировки")

    print("\nИмитация высокорискованной операции (ночь + крупная сумма):")

    # сначала "день" — чтобы спокойно создать клиента и пополнить счёт,
    # не упираясь в ночной хардблок Дня 3 (_check_night_restriction)
    time_switch = _TimeSwitch(datetime(2026, 1, 1, 12, 0))
    risky_bank = Bank(name="RiskBank", time_provider=time_switch)
    risky_client = risky_bank.add_client(Client(full_name="Рискованный Клиент", birth_date=date(1990, 1, 1)))
    risky_acc = risky_bank.open_account(risky_client.client_id, account_type="bank")
    risky_bank.deposit_to_account(risky_acc.get_account_info()["account_id"], 1_000_000)

    # теперь переключаем "часы" банка на 2 часа ночи — и только СЕЙЧАС
    # пытаемся снять деньги, чтобы поймать именно риск-блокировку Дня 5
    # (SuspiciousOperationBlockedError), а не ночной хардблок Дня 3
    time_switch.current = datetime(2026, 1, 1, 2, 0)
    try:
        risky_bank.withdraw_from_account(
            risky_acc.get_account_info()["account_id"], risky_client.client_id, 600000,
        )
    except SuspiciousOperationBlockedError as e:
        print(f"  Заблокировано: {e}")

    print(f"\nОтчёт по подозрительным операциям: {len(risky_bank.get_suspicious_operations_report())} событий")
    print(f"Риск-профиль рискованного клиента: {risky_bank.get_client_risk_profile(risky_client.client_id)}")
    print(f"Статистика ошибок обработки транзакций (данные Дня 4): {bank.get_error_statistics(processor.error_log)}")


def run_full_demo():
    print("ПОЛНАЯ ДЕМОНСТРАЦИЯ ПРОЕКТА (Дни 1-5)")

    demo_day_1_2()

    bank = Bank(name="PyBank")
    alice, bob, alice_acc, alice_usd_acc, bob_acc = demo_day_3(bank)
    processor = demo_day_4(bank, alice, bob, alice_acc, alice_usd_acc, bob_acc)
    demo_day_5(bank, alice, alice_acc, processor)

    print("\n" + "=" * 60)
    print("Готово: все 5 дней отработали в одном сквозном прогоне.")
    print("=" * 60)


if __name__ == "__main__":
    run_full_demo()
