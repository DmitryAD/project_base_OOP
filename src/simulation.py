"""Генерация синтетической нагрузки на банковскую систему."""

import logging
import random
from datetime import datetime, timedelta

from bank import ACCOUNT_CLASSES, Bank
from client import Client
from exceptions import InvalidOperationError
from main import BankAccount
from transaction import (
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionStatus,
    TransactionType,
    filter_client_transactions,
)

logger = logging.getLogger(__name__)

MALE_FIRST_NAMES = ("Борис", "Дмитрий", "Игорь", "Максим", "Олег")
FEMALE_FIRST_NAMES = ("Алина", "Виктория", "Елена", "Ксения", "Наталья")
LAST_NAMES = (
    ("Волков", "Волкова"),
    ("Николаев", "Николаева"),
    ("Смирнов", "Смирнова"),
    ("Кузнецов", "Кузнецова"),
    ("Петров", "Петрова"),
    ("Соколов", "Соколова"),
    ("Морозов", "Морозова"),
    ("Егоров", "Егорова"),
)
CURRENCIES = ("RUB", "USD", "EUR")
ACCOUNT_OPTIONS = {
    "savings": {"min_balance": 500, "monthly_rate": 0.02},
    "premium": {"overdraft_limit": 1000, "withdrawal_fee": 15},
}


class BankSimulation:
    """Создаёт случайных клиентов, счета и транзакции и прогоняет их через банк.

    Случайные значения берутся из собственного генератора random.Random(seed):
    при одинаковом seed прогон воспроизводим, а глобальное состояние
    модуля random не затрагивается. Ошибочные и подозрительные операции
    не задаются вручную — они возникают из правил самой системы
    (лимиты счетов, баланс, риск-анализ).
    """

    MIN_AGE_DAYS = 18 * 366
    MAX_AGE_DAYS = 70 * 365
    LARGE_AMOUNT_PROBABILITY = 0.15
    SIMULATION_PASSWORD = "sim-password"

    def __init__(
        self,
        bank_name: str = "SimBank",
        num_clients: int = 8,
        num_accounts: int = 12,
        num_transactions: int = 40,
        seed: int | None = None,
        time_provider=datetime.now,
    ):
        if num_clients < 1 or num_accounts < num_clients:
            raise InvalidOperationError(
                "Нужен хотя бы один клиент, и счетов должно быть не меньше, чем клиентов."
            )
        self._rng = random.Random(seed)
        self._time_provider = time_provider
        self.bank = Bank(name=bank_name, time_provider=time_provider)
        self.processor = TransactionProcessor(self.bank)
        self.num_clients = num_clients
        self.num_accounts = num_accounts
        self.num_transactions = num_transactions

        self.clients: list[Client] = []
        self.accounts: list[BankAccount] = []
        self.transactions: list[Transaction] = []

    def run(self) -> "BankSimulation":
        """Полный прогон: клиенты, счета, транзакции."""
        self.generate_clients()
        self.generate_accounts()
        self.run_transactions()
        return self

    def generate_clients(self):
        """Создаёт клиентов; дата рождения задаётся сдвигом в днях.

        Сдвиг в днях вместо замены года исключает ошибку для 29 февраля,
        а нижняя граница 18 * 366 дней гарантирует совершеннолетие.
        """
        today = self._time_provider().date()
        for _ in range(self.num_clients):
            is_female = self._rng.random() < 0.5
            first_name = self._rng.choice(FEMALE_FIRST_NAMES if is_female else MALE_FIRST_NAMES)
            male_last_name, female_last_name = self._rng.choice(LAST_NAMES)
            last_name = female_last_name if is_female else male_last_name
            birth_date = today - timedelta(
                days=self._rng.randint(self.MIN_AGE_DAYS, self.MAX_AGE_DAYS)
            )
            client = self.bank.add_client(Client(
                full_name=f"{first_name} {last_name}",
                birth_date=birth_date,
                password=self.SIMULATION_PASSWORD,
            ))
            self.clients.append(client)
        logger.info("Создано клиентов: %d", len(self.clients))

    def generate_accounts(self):
        """Открывает счета так, чтобы у каждого клиента был хотя бы один."""
        for client in self.clients:
            self._open_random_account(client)
        for _ in range(self.num_accounts - len(self.clients)):
            self._open_random_account(self._rng.choice(self.clients))
        logger.info("Открыто счетов: %d", len(self.accounts))

    def _open_random_account(self, client: Client):
        account_type = self._rng.choice(tuple(ACCOUNT_CLASSES))
        account = self.bank.open_account(
            client.client_id,
            account_type=account_type,
            currency=self._rng.choice(CURRENCIES),
            **ACCOUNT_OPTIONS.get(account_type, {}),
        )
        self.bank.deposit_to_account(account.account_id, self._rng.randint(5000, 100000))
        self.accounts.append(account)

    def _random_transaction(self) -> Transaction:
        transaction_type = self._rng.choice(sorted(TransactionType.ALL))
        if self._rng.random() < self.LARGE_AMOUNT_PROBABILITY:
            amount = self._rng.randint(600_000, 900_000)
        else:
            amount = self._rng.randint(50, 5000)
        priority = self._rng.randint(1, 10)

        if transaction_type == TransactionType.DEPOSIT:
            receiver = self._rng.choice(self.accounts)
            return Transaction(
                transaction_type, amount,
                receiver_account_id=receiver.account_id, priority=priority,
            )
        if transaction_type == TransactionType.WITHDRAWAL:
            sender = self._rng.choice(self.accounts)
            return Transaction(
                transaction_type, amount,
                sender_account_id=sender.account_id, priority=priority,
            )
        sender, receiver = self._rng.sample(self.accounts, 2)
        return Transaction(
            transaction_type, amount,
            sender_account_id=sender.account_id,
            receiver_account_id=receiver.account_id,
            priority=priority,
        )

    def run_transactions(self):
        """Ставит транзакции в очередь и обрабатывает их в порядке приоритета."""
        queue = TransactionQueue()
        for _ in range(self.num_transactions):
            transaction = self._random_transaction()
            queue.add(transaction)
            logger.info(
                "[ОЧЕРЕДЬ] %s (%s, %s)",
                transaction.transaction_id, transaction.transaction_type, transaction.amount,
            )

        logger.info("В очереди %d транзакций, начинается обработка", len(queue))
        while (transaction := queue.get_next()) is not None:
            if self.processor.process(transaction):
                logger.info("[ИСПОЛНЕНО] %s", transaction.transaction_id)
            else:
                logger.info(
                    "[ОТКЛОНЕНО] %s: %s", transaction.transaction_id, transaction.failure_reason
                )
            self.transactions.append(transaction)

    def get_client_accounts(self, client_id: str) -> list[BankAccount]:
        return self.bank.get_client_accounts(client_id)

    def get_client_transaction_history(self, client_id: str) -> list[Transaction]:
        return filter_client_transactions(self.transactions, self.bank, client_id)

    def get_client_risk_profile(self, client_id: str) -> dict:
        return self.bank.get_client_risk_profile(client_id)

    def get_most_active_client(self) -> Client:
        return max(self.clients, key=lambda c: len(self.get_client_transaction_history(c.client_id)))

    def get_top_clients(self, n: int = 3, currency: str = "RUB") -> list:
        return self.bank.get_clients_ranking(currency=currency)[:n]

    def get_transaction_statistics(self) -> dict:
        total = len(self.transactions)
        completed = sum(1 for t in self.transactions if t.status == TransactionStatus.COMPLETED)
        failed = sum(1 for t in self.transactions if t.status == TransactionStatus.FAILED)
        by_type: dict[str, int] = {}
        for transaction in self.transactions:
            by_type[transaction.transaction_type] = by_type.get(transaction.transaction_type, 0) + 1
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "success_rate": round(completed / total * 100, 1) if total else 0.0,
            "by_type": by_type,
        }

    def get_total_balance(self) -> dict:
        return self.bank.get_total_balance()
