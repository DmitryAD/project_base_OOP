"""Транзакции: модель операции, приоритетная очередь и обработчик."""

import heapq
import itertools
import uuid
from datetime import datetime
from decimal import Decimal

from exceptions import (
    AccountClosedError,
    AccountFrozenError,
    AccountNotFoundError,
    CurrencyConversionError,
    InsufficientFundsError,
    InvalidOperationError,
    NightOperationRestrictedError,
    SuspiciousOperationBlockedError,
    TransactionNotFoundError,
)
from main import ZERO, round_money, to_decimal


class TransactionType:
    """Типы денежных операций."""

    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    INTERNAL_TRANSFER = "internal_transfer"
    EXTERNAL_TRANSFER = "external_transfer"

    ALL = frozenset({DEPOSIT, WITHDRAWAL, INTERNAL_TRANSFER, EXTERNAL_TRANSFER})
    TRANSFERS = frozenset({INTERNAL_TRANSFER, EXTERNAL_TRANSFER})


class TransactionStatus:
    """Статусы жизненного цикла транзакции."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Transaction:
    """Данные одной денежной операции и её текущее состояние.

    Транзакция не выполняет себя сама: движение денег реализует TransactionProcessor. 
    Благодаря этому транзакцию можно хранить в очереди, логировать и тестировать без банка и счетов.
    """

    def __init__(
        self,
        transaction_type: str,
        amount,
        sender_account_id: str | None = None,
        receiver_account_id: str | None = None,
        priority: int = 0,
        scheduled_at: datetime | None = None,
        transaction_id: str | None = None,
    ):
        self._validate_participants(transaction_type, sender_account_id, receiver_account_id)
        self.transaction_id = transaction_id or uuid.uuid4().hex[:10]
        self.transaction_type = transaction_type
        self.amount = to_decimal(amount)
        self.fee = ZERO
        self.sender_account_id = sender_account_id
        self.receiver_account_id = receiver_account_id
        self.status = TransactionStatus.PENDING
        self.failure_reason: str | None = None
        self.priority = priority
        self.scheduled_at = scheduled_at
        self.created_at = datetime.now()
        self.processed_at: datetime | None = None

    @staticmethod
    def _validate_participants(transaction_type, sender_id, receiver_id):
        if transaction_type not in TransactionType.ALL:
            raise InvalidOperationError(f"Неизвестный тип транзакции: {transaction_type}.")
        needs_sender = transaction_type != TransactionType.DEPOSIT
        needs_receiver = transaction_type != TransactionType.WITHDRAWAL
        if needs_sender and not sender_id:
            raise InvalidOperationError("Для этой операции нужен счёт отправителя.")
        if needs_receiver and not receiver_id:
            raise InvalidOperationError("Для этой операции нужен счёт получателя.")
        if transaction_type in TransactionType.TRANSFERS and sender_id == receiver_id:
            raise InvalidOperationError("Отправитель и получатель перевода совпадают.")

    def mark_processing(self):
        self.status = TransactionStatus.PROCESSING

    def mark_completed(self):
        self.status = TransactionStatus.COMPLETED
        self.processed_at = datetime.now()

    def mark_failed(self, reason: str):
        self.status = TransactionStatus.FAILED
        self.failure_reason = reason
        self.processed_at = datetime.now()

    def mark_cancelled(self):
        self.status = TransactionStatus.CANCELLED

    def __str__(self) -> str:
        return (
            f"Transaction {self.transaction_id} | {self.transaction_type} | "
            f"{self.amount:.2f} (комиссия: {self.fee:.2f}) | "
            f"{self.sender_account_id} -> {self.receiver_account_id} | "
            f"Статус: {self.status}"
        )


def filter_client_transactions(transactions, bank, client_id: str) -> list[Transaction]:
    """Транзакции, в которых клиент участвует как отправитель или получатель."""
    return [
        transaction
        for transaction in transactions
        if client_id in (
            bank.get_client_id_for_account(transaction.sender_account_id),
            bank.get_client_id_for_account(transaction.receiver_account_id),
        )
    ]


class TransactionQueue:
    """Очередь транзакций с приоритетами и отложенным исполнением.

    Основана на heapq (min-heap), поэтому приоритет хранится со знаком
    минус: транзакция с большим priority извлекается раньше. Счётчик
    вставок разрешает равенство приоритетов в порядке FIFO и не даёт
    heapq сравнивать сами объекты Transaction.

    Отмена ленивая: транзакция получает статус CANCELLED и пропускается
    при извлечении, так как удаление из середины кучи стоит O(n).
    """

    def __init__(self):
        self._heap: list[tuple[int, int, Transaction]] = []
        self._counter = itertools.count()
        self._index: dict[str, Transaction] = {}

    def add(self, transaction: Transaction):
        if transaction.status != TransactionStatus.PENDING:
            raise InvalidOperationError("В очередь можно добавить только ожидающую транзакцию.")
        self._push(transaction)
        self._index[transaction.transaction_id] = transaction

    def _push(self, transaction: Transaction):
        heapq.heappush(self._heap, (-transaction.priority, next(self._counter), transaction))

    def cancel(self, transaction_id: str):
        transaction = self._index.get(transaction_id)
        if transaction is None:
            raise TransactionNotFoundError(f"Транзакция {transaction_id} не найдена в очереди.")
        transaction.mark_cancelled()

    def get_next(self, now: datetime | None = None) -> Transaction | None:
        """Извлекает самую приоритетную готовую транзакцию.

        Отменённые транзакции удаляются, отложенные с ещё не наступившим
        временем возвращаются в очередь.
        """
        now = now or datetime.now()
        deferred = []
        result = None

        while self._heap:
            _, _, transaction = heapq.heappop(self._heap)
            if transaction.status == TransactionStatus.CANCELLED:
                self._index.pop(transaction.transaction_id, None)
                continue
            if transaction.scheduled_at is not None and transaction.scheduled_at > now:
                deferred.append(transaction)
                continue
            self._index.pop(transaction.transaction_id, None)
            result = transaction
            break

        for transaction in deferred:
            self._push(transaction)
        return result

    def __len__(self) -> int:
        return sum(
            1 for _, _, transaction in self._heap
            if transaction.status != TransactionStatus.CANCELLED
        )


RATES_TO_RUB = {
    "RUB": Decimal("1"),
    "USD": Decimal("95"),
    "EUR": Decimal("103"),
    "KZT": Decimal("0.19"),
    "CNY": Decimal("13.1"),
}


def default_rate_provider(from_currency: str, to_currency: str) -> Decimal:
    """Курс конвертации через рубль как базовую валюту.

    Имитирует обращение к внешнему сервису курсов. Отсутствие валюты
    в справочнике — постоянная ошибка, поэтому выбрасывается
    InvalidOperationError, а не CurrencyConversionError.
    """
    if from_currency == to_currency:
        return Decimal("1")
    try:
        return RATES_TO_RUB[from_currency] / RATES_TO_RUB[to_currency]
    except KeyError:
        raise InvalidOperationError(
            f"Нет курса конвертации {from_currency} -> {to_currency}."
        ) from None


class TransactionProcessor:
    """Исполнитель транзакций.

    Ошибки делятся на постоянные и временные. Постоянные (нехватка
    средств, заблокированный счёт, запрет по времени или риску) сразу
    переводят транзакцию в FAILED: повтор не изменит результат.
    Временные (CurrencyConversionError) повторяются до max_retries раз.

    Перевод выполняется так, чтобы ни одна ошибка не оставила деньги
    списанными без зачисления: курс получается и зачисление проверяется
    до списания, поэтому повторная попытка не списывает сумму дважды.
    """

    EXTERNAL_FEE_RATE = Decimal("0.01")
    PERMANENT_ERRORS = (
        AccountFrozenError,
        AccountClosedError,
        AccountNotFoundError,
        InsufficientFundsError,
        InvalidOperationError,
        NightOperationRestrictedError,
        SuspiciousOperationBlockedError,
    )

    def __init__(self, bank, rate_provider=default_rate_provider, max_retries: int = 3):
        if max_retries < 1:
            raise InvalidOperationError("max_retries должен быть не меньше 1.")
        self.bank = bank
        self._rate_provider = rate_provider
        self.max_retries = max_retries
        self.error_log: list[dict] = []

    def process(self, transaction: Transaction) -> bool:
        """Обрабатывает транзакцию и возвращает True при успехе.

        Повторно обработать уже завершённую транзакцию нельзя. В журнале
        ошибок attempt=0 означает отказ на этапе предварительных проверок.
        """
        if transaction.status != TransactionStatus.PENDING:
            return False

        transaction.mark_processing()
        transaction.fee = self._calculate_fee(transaction)

        try:
            self._run_pre_checks(transaction)
        except self.PERMANENT_ERRORS as error:
            return self._fail(transaction, error, attempt=0)

        for attempt in range(1, self.max_retries + 1):
            try:
                self._execute(transaction)
            except self.PERMANENT_ERRORS as error:
                return self._fail(transaction, error, attempt)
            except CurrencyConversionError as error:
                self._log_error(transaction, error, attempt)
                continue
            transaction.mark_completed()
            return True

        transaction.mark_failed(
            f"Не удалось получить курс валюты после {self.max_retries} попыток."
        )
        return False

    def _calculate_fee(self, transaction: Transaction) -> Decimal:
        if transaction.transaction_type == TransactionType.EXTERNAL_TRANSFER:
            return round_money(transaction.amount * self.EXTERNAL_FEE_RATE)
        return ZERO

    def _run_pre_checks(self, transaction: Transaction):
        """Проверки, выполняемые один раз до попыток исполнения."""
        self.bank.check_night_restriction()
        if transaction.receiver_account_id is not None:
            self.bank.get_account(transaction.receiver_account_id)
        if transaction.transaction_type == TransactionType.DEPOSIT:
            return
        self.bank.get_account(transaction.sender_account_id)
        self.bank.check_operation_risk(
            client_id=self.bank.get_client_id_for_account(transaction.sender_account_id),
            amount=transaction.amount,
            receiver_account_id=transaction.receiver_account_id,
        )

    def _execute(self, transaction: Transaction):
        if transaction.transaction_type == TransactionType.DEPOSIT:
            self.bank.get_account(transaction.receiver_account_id).deposit(transaction.amount)
            return

        sender = self.bank.get_account(transaction.sender_account_id)
        if transaction.transaction_type == TransactionType.WITHDRAWAL:
            sender.withdraw(transaction.amount)
            return

        receiver = self.bank.get_account(transaction.receiver_account_id)
        rate = to_decimal(self._rate_provider(sender.currency, receiver.currency))
        credited = round_money(transaction.amount * rate)
        receiver.validate_deposit(credited)
        sender.withdraw(transaction.amount + transaction.fee)
        receiver.deposit(credited)

    def _fail(self, transaction: Transaction, error: Exception, attempt: int) -> bool:
        self._log_error(transaction, error, attempt)
        transaction.mark_failed(str(error))
        return False

    def _log_error(self, transaction: Transaction, error: Exception, attempt: int):
        self.error_log.append({
            "transaction_id": transaction.transaction_id,
            "error": str(error),
            "error_type": type(error).__name__,
            "attempt": attempt,
            "timestamp": datetime.now(),
        })
