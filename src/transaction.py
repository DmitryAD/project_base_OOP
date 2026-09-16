import heapq
import itertools
import uuid
from datetime import datetime

from exceptions import (
    AccountFrozenError,
    AccountClosedError,
    AccountNotFoundError,
    InsufficientFundsError,
    InvalidOperationError,
    CurrencyConversionError,
    TransactionNotFoundError,
    SuspiciousOperationBlockedError,
)


class TransactionType:
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    INTERNAL_TRANSFER = "internal_transfer"
    EXTERNAL_TRANSFER = "external_transfer"


class TransactionStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Transaction:
    """
    Модель одной денежной операции: кто кому сколько и в какой валюте,
    с каким приоритетом и (опционально) отложенным временем исполнения.

    Сама Transaction ничего не ИСПОЛНЯЕТ — она только хранит данные
    и своё текущее состояние. Реальное движение денег делает отдельный
    класс TransactionProcessor (см. ниже). Это разделение — данные
    отдельно от логики их обработки — намеренное архитектурное решение,
    а не просто стиль: так Transaction можно свободно сериализовать,
    класть в очередь, логировать, тестировать — не таща за собой
    зависимость от Bank и реальных счетов.
    """

    def __init__(
        self,
        transaction_type: str,
        amount: float,
        sender_account_id: str = None,
        receiver_account_id: str = None,
        priority: int = 0,
        scheduled_at: datetime = None,
        transaction_id: str = None,
    ):
        self.transaction_id = transaction_id or self._generate_id()
        self.transaction_type = transaction_type
        self.amount = amount
        self.fee = 0.0
        self.sender_account_id = sender_account_id
        self.receiver_account_id = receiver_account_id
        self.status = TransactionStatus.PENDING
        self.failure_reason = None
        self.priority = priority
        self.scheduled_at = scheduled_at
        self.created_at = datetime.now()
        self.processed_at = None

    @staticmethod
    def _generate_id() -> str:
        return str(uuid.uuid4().int)[:10]

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

    def __str__(self):
        return (
            f"Transaction {self.transaction_id} | {self.transaction_type} | "
            f"{self.amount:.2f} (комиссия: {self.fee:.2f}) | "
            f"{self.sender_account_id} -> {self.receiver_account_id} | "
            f"Статус: {self.status}"
        )


class TransactionQueue:
    """
    Приоритетная очередь транзакций поверх модуля heapq.

    heapq — встроенный модуль Python, реализующий структуру данных
    "куча" (heap): особый способ хранить коллекцию так, чтобы наименьший
    элемент всегда был мгновенно доступен (heap[0]), а вставка и
    извлечение занимали O(log n) — гораздо быстрее, чем пересортировка
    всего списка (O(n log n)) при каждом добавлении. Это стандартный,
    "боевой" инструмент для построения очередей с приоритетом — то же
    самое используют, например, планировщики задач в реальных системах.

    heapq — это MIN-heap: наверху всегда оказывается элемент с
    НАИМЕНЬШИМ значением ключа. У нас же приоритет устроен наоборот —
    чем БОЛЬШЕ число (например, priority=10), тем важнее транзакция и
    тем раньше её нужно обработать. Поэтому при вставке мы кладём в
    кучу priority СО ЗНАКОМ МИНУС (-priority) — тогда самая
    приоритетная транзакция (с большим priority) превращается в
    наименьшее число и оказывается наверху кучи, как heapq и ожидает.
    """

    def __init__(self):
        self._heap = []
        self._counter = itertools.count()
        self._index = {}

    def add(self, transaction: Transaction):
        """
        itertools.count() — генератор, который при каждом вызове next()
        выдаёт следующее целое число (0, 1, 2, 3, ...) бесконечно.
        Используем его как "тай-брейкер" (tie-breaker): heapq сравнивает
        элементы кортежа по очереди — сначала -priority, и если у двух
        транзакций приоритет совпал, heapq попытался бы сравнить СЛЕДУЮЩИЙ
        элемент кортежа. Если бы это сразу был объект Transaction, Python
        не знал бы, как сравнить "Transaction < Transaction" (мы не
        определяли для него __lt__), и упал бы с TypeError. next(self._counter)
        — уникальное, всегда возрастающее число — гарантирует, что до
        сравнения самих объектов Transaction дело никогда не дойдёт:
        два разных вызова next() никогда не совпадут.
        """
        entry = (-transaction.priority, next(self._counter), transaction)
        heapq.heappush(self._heap, entry)
        self._index[transaction.transaction_id] = transaction

    def cancel(self, transaction_id: str):
        """
        Отмена через "ленивое удаление" (lazy deletion) — распространённый
        приём при работе с heapq. Удалить произвольный элемент из
        СЕРЕДИНЫ кучи — дорогая операция (O(n), нужно перестраивать
        структуру). Вместо этого мы просто помечаем транзакцию статусом
        CANCELLED прямо здесь, а сам объект остаётся физически лежать в
        куче до своей очереди. get_next() при извлечении сам проверяет
        статус и молча пропускает отменённые транзакции — куча "лениво"
        избавляется от мусора только когда до него доходит очередь.
        """
        transaction = self._index.get(transaction_id)
        if transaction is None:
            raise TransactionNotFoundError(f"Транзакция {transaction_id} не найдена в очереди.")
        transaction.mark_cancelled()

    def get_next(self, now: datetime = None):
        """
        Извлекает следующую готовую к обработке транзакцию с учётом
        приоритета, пропуская отменённые и ещё не наступившие
        (отложенные) операции.
        """
        now = now or datetime.now()
        deferred = []
        result = None

        while self._heap:
            _, _, transaction = heapq.heappop(self._heap)

            if transaction.status == TransactionStatus.CANCELLED:
                continue

            if transaction.scheduled_at is not None and transaction.scheduled_at > now:
                # ещё не время исполнять — временно откладываем в сторону,
                # но не теряем: вернём обратно в кучу после цикла
                deferred.append((-transaction.priority, next(self._counter), transaction))
                continue

            result = transaction
            break

        for entry in deferred:
            heapq.heappush(self._heap, entry)

        return result

    def __len__(self):
        return len(self._heap)


EXCHANGE_RATES = {
    ("USD", "RUB"): 95.0,
    ("RUB", "USD"): 1 / 95.0,
    ("EUR", "RUB"): 103.0,
    ("RUB", "EUR"): 1 / 103.0,
    ("USD", "EUR"): 0.92,
    ("EUR", "USD"): 1 / 0.92,
}


def default_rate_provider(from_currency: str, to_currency: str) -> float:
    """
    Функция по умолчанию для получения курса конвертации.

    В реальной системе это был бы поход во внешний сервис (API
    Центробанка, биржевой фид и т.д.) — то есть операция, которая
    МОЖЕТ временно не сработать (сеть недоступна, сервис лежит) и
    имеет смысл повторить попытку. Здесь это упрощено до словаря, но
    сигнатура функции спроектирована так, будто это реальный сетевой
    вызов — именно поэтому TransactionProcessor ниже умеет её
    ретраить (повторять при сбое), а не просто дёргает словарь напрямую.
    """
    if from_currency == to_currency:
        return 1.0
    rate = EXCHANGE_RATES.get((from_currency, to_currency))
    if rate is None:
        raise CurrencyConversionError(
            f"Нет курса конвертации {from_currency} -> {to_currency}."
        )
    return rate


class TransactionProcessor:
    """
    Исполнитель транзакций: списывает/зачисляет деньги на реальных
    счетах через Bank, считает комиссию за внешние переводы,
    конвертирует валюту и логирует ошибки.

    rate_provider передаётся как ЗАВИСИМОСТЬ (тот же приём dependency
    injection, что мы применили для time_provider в Bank) — по
    умолчанию используется default_rate_provider, но в тестах можно
    подставить свою функцию, которая, например, специально падает
    первые два раза, чтобы проверить логику повторных попыток.
    """

    EXTERNAL_FEE_RATE = 0.01  # 1% комиссии с суммы для внешних переводов

    def __init__(self, bank, rate_provider=default_rate_provider, max_retries: int = 3):
        self.bank = bank
        self._rate_provider = rate_provider
        self.max_retries = max_retries
        self.error_log = []

    def _log_error(self, transaction: Transaction, error: Exception, attempt: int):
        self.error_log.append({
            "transaction_id": transaction.transaction_id,
            "error": str(error),
            "error_type": type(error).__name__,
            "attempt": attempt,
            "timestamp": datetime.now(),
        })

    def _calculate_fee(self, transaction: Transaction) -> float:
        if transaction.transaction_type == TransactionType.EXTERNAL_TRANSFER:
            return round(transaction.amount * self.EXTERNAL_FEE_RATE, 2)
        return 0.0

    def process(self, transaction: Transaction) -> bool:
        """
        Обрабатывает одну транзакцию, с ретраями для временных сбоев.

        Ключевая идея — РАЗДЕЛЕНИЕ ошибок на два вида:

        1. ПОСТОЯННЫЕ (permanent) — счёт заморожен, счёт не найден, не
           хватает денег, некорректная сумма. Повторная попытка ничего
           не изменит: если денег не хватает сейчас, их не станет
           больше через миллисекунду. Такие ошибки сразу помечают
           транзакцию FAILED, без ретраев.

        2. ВРЕМЕННЫЕ (transient) — не получилось получить курс валюты
           (в реальности — сбой сети/внешнего сервиса). Здесь есть
           смысл попробовать ещё раз: возможно, при следующей попытке
           сервис уже ответит. Именно это различение — стандартная
           практика в реальных системах: слепо ретраить ВСЁ подряд
           (включая постоянные ошибки) — плохая практика, она просто
           тратит время и ресурсы, не решая проблему.
        """
        if transaction.status == TransactionStatus.CANCELLED:
            return False

        transaction.mark_processing()
        transaction.fee = self._calculate_fee(transaction)

                # === НОВОЕ (День 5) ===
        if transaction.transaction_type != TransactionType.DEPOSIT:
            client_id = self.bank.get_client_id_for_account(transaction.sender_account_id)
            try:
                self.bank.check_operation_risk(
                    client_id=client_id,
                    amount=transaction.amount,
                    receiver_account_id=transaction.receiver_account_id,
                )
            except SuspiciousOperationBlockedError as e:
                self._log_error(transaction, e, attempt=0)
                transaction.mark_failed(str(e))
                return False
        # === КОНЕЦ НОВОГО ===

        attempt = 0
        while attempt < self.max_retries:
            attempt += 1
            try:
                self._execute(transaction)
                transaction.mark_completed()
                return True

            except (
                AccountFrozenError,
                AccountClosedError,
                AccountNotFoundError,
                InsufficientFundsError,
                InvalidOperationError,
            ) as e:
                self._log_error(transaction, e, attempt)
                transaction.mark_failed(str(e))
                return False

            except CurrencyConversionError as e:
                self._log_error(transaction, e, attempt)
                if attempt >= self.max_retries:
                    transaction.mark_failed(
                        f"Не удалось получить курс валюты после {attempt} попыток: {e}"
                    )
                    return False
                # иначе — просто продолжаем цикл while, то есть повторяем попытку

        return False

    def _execute(self, transaction: Transaction):
        """
        Собственно движение денег. Все ошибки (заморожен счёт,
        не хватает средств и т.д.) просто ПРОБРАСЫВАЮТСЯ наружу —
        их ловит process() выше. _execute сам ничего не решает про
        ретраи, это не его ответственность (разделение ответственности,
        как и в остальном проекте).
        """
        if transaction.transaction_type == TransactionType.DEPOSIT:
            account = self.bank.get_account(transaction.receiver_account_id)
            account.deposit(transaction.amount)
            return

        if transaction.transaction_type == TransactionType.WITHDRAWAL:
            account = self.bank.get_account(transaction.sender_account_id)
            account.withdraw(transaction.amount)
            return

        # INTERNAL_TRANSFER и EXTERNAL_TRANSFER обрабатываются одинаково:
        # разница между ними только в комиссии (см. _calculate_fee выше)
        sender = self.bank.get_account(transaction.sender_account_id)
        receiver = self.bank.get_account(transaction.receiver_account_id)

        sender_currency = sender.get_account_info()["currency"]
        receiver_currency = receiver.get_account_info()["currency"]

        total_debit = transaction.amount + transaction.fee
        # sender.withdraw() САМ проверит статус счёта, минимальный баланс
        # и правило "нельзя уйти в минус, кроме Premium" — вся эта логика
        # уже живёт в классах счетов с Дня 1-2, здесь мы её не дублируем
        sender.withdraw(total_debit)

        rate = self._rate_provider(sender_currency, receiver_currency)
        credited_amount = round(transaction.amount * rate, 2)
        receiver.deposit(credited_amount)


def demo():
    from datetime import timedelta
    from bank import Bank
    from client import Client

    print("=== Демонстрация системы транзакций (День 4) ===\n")

    bank = Bank(name="PyBank")
    processor = TransactionProcessor(bank)

    from datetime import date
    alice = bank.add_client(Client(full_name="Алина Волкова", birth_date=date(1995, 6, 20), password="qwerty"))
    bob = bank.add_client(Client(full_name="Борис Николаев", birth_date=date(1988, 3, 15), password="secret"))

    alice_acc = bank.open_account(alice.client_id, account_type="bank", currency="RUB")
    alice_usd_acc = bank.open_account(alice.client_id, account_type="premium", currency="USD", overdraft_limit=500)
    bob_acc = bank.open_account(bob.client_id, account_type="bank", currency="RUB")

    bank.deposit_to_account(alice_acc.get_account_info()["account_id"], 50000)
    bank.deposit_to_account(alice_usd_acc.get_account_info()["account_id"], 1000)
    bank.deposit_to_account(bob_acc.get_account_info()["account_id"], 5000)

    alice_id = alice_acc.get_account_info()["account_id"]
    alice_usd_id = alice_usd_acc.get_account_info()["account_id"]
    bob_id = bob_acc.get_account_info()["account_id"]

    """
    Формируем 10 транзакций, как требует задание: разные типы,
    приоритеты и одна отложенная — чтобы продемонстрировать очередь
    и обработчик во всей их логике, а не только "счастливый путь".
    """
    transactions = [
        Transaction(TransactionType.DEPOSIT, 1000, receiver_account_id=alice_id, priority=1),
        Transaction(TransactionType.WITHDRAWAL, 200, sender_account_id=bob_id, priority=1),
        Transaction(TransactionType.INTERNAL_TRANSFER, 2000, sender_account_id=alice_id, receiver_account_id=bob_id, priority=5),
        Transaction(TransactionType.EXTERNAL_TRANSFER, 3000, sender_account_id=alice_id, receiver_account_id=bob_id, priority=3),
        Transaction(TransactionType.INTERNAL_TRANSFER, 100000, sender_account_id=bob_id, receiver_account_id=alice_id, priority=2),  # упадёт: не хватит средств
        Transaction(TransactionType.INTERNAL_TRANSFER, 300, sender_account_id=alice_usd_id, receiver_account_id=bob_id, priority=4),  # сработает конвертация USD -> RUB
        Transaction(TransactionType.WITHDRAWAL, 100, sender_account_id=alice_id, priority=1,
                    scheduled_at=datetime.now() + timedelta(hours=1)),  # отложенная — обработается не сразу
        Transaction(TransactionType.DEPOSIT, 500, receiver_account_id=bob_id, priority=10),  # высокий приоритет — обработается одним из первых
        Transaction(TransactionType.EXTERNAL_TRANSFER, 1500, sender_account_id=alice_usd_id, receiver_account_id=bob_id, priority=1, transaction_id="TO_CANCEL"),
        Transaction(TransactionType.INTERNAL_TRANSFER, 50, sender_account_id=bob_id, receiver_account_id=alice_id, priority=1),
    ]

    queue = TransactionQueue()
    for transaction in transactions:
        queue.add(transaction)

    queue.cancel("TO_CANCEL")

    print(f"В очереди {len(queue)} транзакций. Начинаем обработку:\n")

    processed_count = 0
    while True:
        transaction = queue.get_next()
        if transaction is None:
            break
        processor.process(transaction)
        print(transaction)
        processed_count += 1

    print(f"\nОбработано транзакций: {processed_count}")
    print(f"Ошибок в логе процессора: {len(processor.error_log)}")
    for entry in processor.error_log:
        print(f"  {entry['transaction_id']}: {entry['error']}")


if __name__ == "__main__":
    demo()
