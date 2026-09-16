"""
День 6: комплексная демонстрационная симуляция всей банковской системы.

Этот модуль НЕ меняет ничего в существующих классах (Bank, Client,
Transaction, TransactionProcessor) — он целиком построен поверх их
публичного API. BankSimulation играет роль "оркестратора" верхнего
уровня, который дирижирует готовыми кирпичиками системы, а не лезет
им во внутренности.
"""

import random
from datetime import date

from client import Client
from bank import Bank
from transaction import Transaction, TransactionType, TransactionStatus, TransactionQueue, TransactionProcessor


FIRST_NAMES = ["Алина", "Борис", "Виктория", "Дмитрий", "Елена", "Игорь", "Ксения", "Максим", "Наталья", "Олег"]
LAST_NAMES = ["Волкова", "Николаев", "Смирнова", "Кузнецов", "Петрова", "Соколов", "Морозова", "Егоров", "Васильева", "Фёдоров"]
ACCOUNT_TYPES = ["bank", "savings", "premium", "investment"]
CURRENCIES = ["RUB", "USD", "EUR"]


class BankSimulation:
    """
    Генерирует случайных клиентов и счета, прогоняет через них случайные
    транзакции (включая заведомо ошибочные и подозрительные по своей
    природе — не подстроенные вручную), ведёт полную историю и умеет
    строить итоговые отчёты.
    """

    def __init__(
        self,
        bank_name: str = "SimBank",
        num_clients: int = 8,
        num_accounts: int = 12,
        num_transactions: int = 40,
        seed: int = None,
    ):
        """
        random.seed(seed) делает "случайные" числа ВОСПРОИЗВОДИМЫМИ: при
        одном и том же seed random каждый раз выдаёт одну и ту же
        последовательность значений. Это критично для отладки и тестов —
        можно повторить точно такой же прогон и получить те же цифры,
        вместо того чтобы гоняться за багом, который проявляется
        "иногда, в зависимости от того, как повезло со случайностью".
        seed=None (по умолчанию) — используется системное случайное
        зерно, каждый запуск будет отличаться от предыдущего.
        """
        if seed is not None:
            random.seed(seed)

        self.bank = Bank(name=bank_name)
        self.processor = TransactionProcessor(self.bank)
        self.num_clients = num_clients
        self.num_accounts = num_accounts
        self.num_transactions = num_transactions

        self.clients: list[Client] = []
        self.accounts: list = []  # объекты счетов (любого из 4 типов)

        # transaction_log — полная история КАЖДОЙ обработанной транзакции
        # (и успешной, и неуспешной). Нужна для отчётов ниже.
        self.transaction_log: list[dict] = []

    # ---------- инициализация ----------

    def generate_clients(self):
        """Создаёт self.num_clients случайных клиентов."""
        for _ in range(self.num_clients):
            first = random.choice(FIRST_NAMES)  # случайный элемент списка
            last = random.choice(LAST_NAMES)
            age_years = random.randint(18, 70)  # случайное целое, включая обе границы
            birth_date = date.today().replace(year=date.today().year - age_years)
            client = self.bank.add_client(Client(
                full_name=f"{first} {last}",
                birth_date=birth_date,
                password="password123",
            ))
            self.clients.append(client)
        print(f"Создано клиентов: {len(self.clients)}")

    def generate_accounts(self):
        """
        Открывает self.num_accounts счетов так, чтобы у КАЖДОГО клиента
        было хотя бы по одному — иначе при полностью случайном
        распределении кому-то может не достаться ни одного счёта, что
        и нереалистично для банка, и обесценивает демонстрацию
        пользовательских сценариев ниже (нечего будет показать).
        Остаток от целочисленного деления раздаётся случайным клиентам.
        """
        accounts_per_client = max(1, self.num_accounts // self.num_clients)
        remaining = self.num_accounts

        for client in self.clients:
            if remaining <= 0:
                break
            for _ in range(min(accounts_per_client, remaining)):
                self._open_random_account(client)
                remaining -= 1

        while remaining > 0:
            client = random.choice(self.clients)
            self._open_random_account(client)
            remaining -= 1

        print(f"Открыто счетов: {len(self.accounts)}")

    def _open_random_account(self, client: Client):
        """Открывает один случайный счёт указанному клиенту и пополняет его."""
        account_type = random.choice(ACCOUNT_TYPES)
        currency = random.choice(CURRENCIES)

        # у разных типов счетов разные допустимые именованные параметры —
        # собираем их условно, а не передаём одно и то же всем подряд
        kwargs = {}
        if account_type == "savings":
            kwargs = {"min_balance": 500, "monthly_rate": 0.02}
        elif account_type == "premium":
            kwargs = {"overdraft_limit": 1000, "withdrawal_fee": 15}

        account = self.bank.open_account(
            client.client_id, account_type=account_type, currency=currency, **kwargs
        )
        starting_balance = random.randint(5000, 100000)
        self.bank.deposit_to_account(account.get_account_info()["account_id"], starting_balance)
        self.accounts.append(account)

    # ---------- симуляция транзакций ----------

    def _random_transaction(self) -> Transaction:
        """
        Строит одну случайную транзакцию. ~15% транзакций получают
        намеренно крупную сумму (600 000-900 000) — дальше система САМА,
        уже существующей логикой (лимит счёта из Дня 1-2, риск-анализ
        Дня 5), решает, пройдёт операция, упадёт с ошибкой или будет
        заблокирована как подозрительная.
        """
        transaction_type = random.choice([
            TransactionType.DEPOSIT,
            TransactionType.WITHDRAWAL,
            TransactionType.INTERNAL_TRANSFER,
            TransactionType.EXTERNAL_TRANSFER,
        ])

        # random.random() — случайное float число в диапазоне [0.0, 1.0)
        if random.random() < 0.15:
            amount = random.randint(600_000, 900_000)
        else:
            amount = random.randint(50, 5000)

        priority = random.randint(1, 10)

        if transaction_type == TransactionType.DEPOSIT:
            receiver = random.choice(self.accounts)
            return Transaction(
                transaction_type, amount,
                receiver_account_id=receiver.get_account_info()["account_id"],
                priority=priority,
            )

        if transaction_type == TransactionType.WITHDRAWAL:
            sender = random.choice(self.accounts)
            return Transaction(
                transaction_type, amount,
                sender_account_id=sender.get_account_info()["account_id"],
                priority=priority,
            )

        """
        Переводы: random.sample(список, 2) выбирает 2 РАЗНЫХ элемента без
        повторов — в отличие от random.choice, который мог бы случайно
        выбрать один и тот же счёт дважды (перевод "самому себе" не
        показателен для демонстрации).
        """
        sender_account, receiver_account = random.sample(self.accounts, 2)
        return Transaction(
            transaction_type, amount,
            sender_account_id=sender_account.get_account_info()["account_id"],
            receiver_account_id=receiver_account.get_account_info()["account_id"],
            priority=priority,
        )

    def run_transactions(self):
        """
        Генерирует self.num_transactions транзакций, кладёт их в очередь,
        затем обрабатывает одну за другой, логируя каждый шаг: попадание
        в очередь, исполнение или отклонение.
        """
        queue = TransactionQueue()
        for _ in range(self.num_transactions):
            transaction = self._random_transaction()
            queue.add(transaction)
            print(f"[ОЧЕРЕДЬ] {transaction.transaction_id} "
                  f"({transaction.transaction_type}, {transaction.amount})")

        print(f"\nВ очереди {len(queue)} транзакций. Начинаем обработку...\n")

        while True:
            transaction = queue.get_next()
            if transaction is None:
                break

            success = self.processor.process(transaction)

            if success:
                print(f"[ИСПОЛНЕНО] {transaction.transaction_id}")
            else:
                print(f"[ОТКЛОНЕНО] {transaction.transaction_id}: {transaction.failure_reason}")

            self.transaction_log.append({"transaction": transaction, "status": transaction.status})

    # ---------- пользовательские сценарии ----------

    def show_client_accounts(self, client_id: str):
        client = self.bank.clients[client_id]
        print(f"\nСчета клиента {client.full_name}:")
        for account_id in client.account_ids:
            print(f"  {self.bank.get_account(account_id)}")

    def get_client_transaction_history(self, client_id: str) -> list:
        """
        Собирает историю клиента ПОСТФАКТУМ, а не заранее по отдельному
        списку на каждого клиента: транзакция знает только account_id,
        а не client_id, поэтому сверяем через get_client_id_for_account
        (готовый публичный метод Bank с Дня 5).
        """
        history = []
        for entry in self.transaction_log:
            t = entry["transaction"]
            sender_client = self.bank.get_client_id_for_account(t.sender_account_id) if t.sender_account_id else None
            receiver_client = self.bank.get_client_id_for_account(t.receiver_account_id) if t.receiver_account_id else None
            if client_id in (sender_client, receiver_client):
                history.append(t)
        return history

    def show_client_history(self, client_id: str):
        client = self.bank.clients[client_id]
        history = self.get_client_transaction_history(client_id)
        print(f"\nИстория операций клиента {client.full_name} ({len(history)} шт.):")
        for t in history:
            print(f"  {t}")

    def show_client_suspicious_operations(self, client_id: str):
        client = self.bank.clients[client_id]
        profile = self.bank.get_client_risk_profile(client_id)
        print(f"\nРиск-профиль клиента {client.full_name}: {profile}")

    # ---------- отчёты ----------

    def get_top_clients(self, n: int = 3, currency: str = "RUB") -> list:
        """
        get_clients_ranking уже возвращает список (client, total),
        отсортированный по убыванию — срез [:n] просто берёт первые
        n элементов.
        """
        ranking = self.bank.get_clients_ranking(currency=currency)
        return ranking[:n]

    def print_top_clients(self, n: int = 3):
        print(f"\nТоп-{n} клиентов по балансу (RUB):")
        for client, total in self.get_top_clients(n):
            print(f"  {client.full_name}: {total:.2f}")

    def get_transaction_statistics(self) -> dict:
        """Базовая статистика по всем обработанным транзакциям."""
        total = len(self.transaction_log)
        completed = sum(1 for e in self.transaction_log if e["status"] == TransactionStatus.COMPLETED)
        failed = sum(1 for e in self.transaction_log if e["status"] == TransactionStatus.FAILED)

        by_type = {}
        for entry in self.transaction_log:
            t_type = entry["transaction"].transaction_type
            by_type[t_type] = by_type.get(t_type, 0) + 1

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / total * 100, 1) if total else 0.0,
            "by_type": by_type,
        }

    def print_transaction_statistics(self):
        stats = self.get_transaction_statistics()
        print(f"\nСтатистика транзакций:")
        print(f"  Всего: {stats['total']}, успешно: {stats['completed']}, "
              f"отклонено: {stats['failed']} (успешность: {stats['success_rate']}%)")
        print(f"  По типам: {stats['by_type']}")

    def print_total_balance(self):
        print(f"\nОбщий баланс банка по валютам: {self.bank.get_total_balance()}")


def run_day_6_demo():
    print("=" * 60)
    print("ДЕНЬ 6: Комплексная демонстрация банковской системы")
    print("=" * 60)

    # seed=42 — фиксированное зерно, чтобы твой запуск давал те же
    # цифры, что и у меня, и было удобно сверяться при разборе
    sim = BankSimulation(num_clients=8, num_accounts=12, num_transactions=40, seed=42)
    sim.generate_clients()
    sim.generate_accounts()
    sim.run_transactions()

    print("\n" + "=" * 60)
    print("ПОЛЬЗОВАТЕЛЬСКИЕ СЦЕНАРИИ (на примере самого активного клиента)")
    print("=" * 60)
    # max(iterable, key=функция) — находит элемент с МАКСИМАЛЬНЫМ значением
    # функции-ключа. Здесь key — lambda, которая для каждого клиента
    # считает длину его истории операций; max выбирает клиента с самой
    # длинной историей, чтобы в демонстрации было реально что показать
    sample_client = max(sim.clients, key=lambda c: len(sim.get_client_transaction_history(c.client_id)))
    sim.show_client_accounts(sample_client.client_id)
    sim.show_client_history(sample_client.client_id)
    sim.show_client_suspicious_operations(sample_client.client_id)

    print("\n" + "=" * 60)
    print("ОТЧЁТЫ")
    print("=" * 60)
    sim.print_top_clients(3)
    sim.print_transaction_statistics()
    sim.print_total_balance()


if __name__ == "__main__":
    run_day_6_demo()
