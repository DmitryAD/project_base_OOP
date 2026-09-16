from datetime import datetime, time
from collections import Counter

from client import Client, ClientStatus
from main import BankAccount, SavingsAccount, PremiumAccount, InvestmentAccount
from exceptions import (
    InvalidOperationError,
    ClientNotFoundError,
    AccountNotFoundError,
    AuthenticationError,
    ClientBlockedError,
    NightOperationRestrictedError,
    SuspiciousOperationBlockedError,  # === НОВОЕ (День 5) ===
)
from audit import AuditLog, AuditSeverity          # === НОВОЕ (День 5) ===
from risk import RiskAnalyzer, RiskLevel            # === НОВОЕ (День 5) ===

# сопоставление строкового имени типа счёта -> класс, который его реализует.
# Так open_account() может создавать любой тип счёта по одной строке,
# не имея кучи if/elif на каждый тип
ACCOUNT_CLASSES = {
    "bank": BankAccount,
    "savings": SavingsAccount,
    "premium": PremiumAccount,
    "investment": InvestmentAccount,
}

NIGHT_START = time(0, 0)   # 00:00
NIGHT_END = time(5, 0)     # 05:00
MAX_LOGIN_ATTEMPTS = 3


class Bank:
    """Управляющий класс: хранит клиентов и счета, обеспечивает
    аутентификацию, безопасность и агрегированную статистику."""

    SUSPICIOUS_AMOUNT_THRESHOLD = 500_000.0  # снятие выше этой суммы помечается как подозрительное

    def __init__(
        self,
        name: str,
        time_provider=datetime.now,
        audit_log: AuditLog = None,          # === НОВОЕ (День 5) ===
        risk_analyzer: RiskAnalyzer = None,  # === НОВОЕ (День 5) ===
    ):
        self.name = name
        self._time_provider = time_provider

        self.clients: dict[str, Client] = {}     # client_id -> Client
        self.accounts: dict[str, object] = {}     # account_id -> объект счёта (любого из 4 типов)
        self._login_attempts: dict[str, int] = {}  # client_id -> счётчик неверных попыток входа
        self.suspicious_log: list[dict] = []       # список зафиксированных подозрительных событий (День 3, оставлен для совместимости)

        # === НОВОЕ (День 5) ===
        # audit_log/risk_analyzer передаются как зависимости (тот же приём
        # dependency injection, что и time_provider выше) — если не передали,
        # создаём дефолтные. `is None`, а не просто `if audit_log:` —
        # потому что пустой объект (например, AuditLog без событий) не
        # должен считаться "не передан", если бы кто-то захотел так сделать.
        self.audit_log = audit_log if audit_log is not None else AuditLog(time_provider=time_provider)
        self.risk_analyzer = risk_analyzer if risk_analyzer is not None else RiskAnalyzer(time_provider=time_provider)

        self._account_owners: dict[str, str] = {}          # account_id -> client_id (быстрый обратный поиск)
        self._client_operation_history: dict[str, list] = {}   # client_id -> список timestamp'ов операций
        self._client_known_receivers: dict[str, set] = {}      # client_id -> множество account_id, на которые уже переводили
        # === КОНЕЦ НОВОГО ===

    # ---------- внутренние помощники ----------

    def _get_client(self, client_id: str) -> Client:
        client = self.clients.get(client_id)
        if client is None:
            raise ClientNotFoundError(f"Клиент с ID {client_id} не найден.")
        return client

    def _get_account(self, account_id: str):
        account = self.accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(f"Счёт с ID {account_id} не найден.")
        return account

    def get_account(self, account_id: str):
        """
        Публичный доступ к счёту по ID.

        В отличие от _get_account (с подчёркиванием — внутренний метод
        самого Bank), этот метод предназначен для использования ДРУГИМИ
        классами, которые сотрудничают с Bank, но не являются его частью —
        например, TransactionProcessor.
        """
        return self._get_account(account_id)

    def _check_night_restriction(self):
        current_time = self._time_provider().time()
        if NIGHT_START <= current_time < NIGHT_END:
            raise NightOperationRestrictedError(
                "Операции недоступны с 00:00 до 05:00."
            )

    def _flag_suspicious(self, client_id: str, reason: str):
        self.suspicious_log.append({
            "client_id": client_id,
            "reason": reason,
            "timestamp": self._time_provider(),
        })

    # === НОВОЕ (День 5) ===
    def get_client_id_for_account(self, account_id: str) -> str:
        """
        Обратный поиск: по account_id находит client_id владельца.
        Нужен TransactionProcessor'у — он знает только account_id
        (sender_account_id/receiver_account_id), а риск-анализ считается
        по клиенту, не по счёту.
        """
        return self._account_owners.get(account_id)

    def check_operation_risk(self, client_id: str, amount: float, receiver_account_id: str = None) -> str:
        """
        Единая точка входа для риск-анализа: вызывается и из
        withdraw_from_account (прямые операции), и из
        TransactionProcessor.process (операции через очередь), чтобы
        логика не дублировалась в двух местах.

        Возвращает risk_level, если операция разрешена.
        Бросает SuspiciousOperationBlockedError, если риск высокий —
        операция в этом случае НЕ выполняется вызывающим кодом.
        """
        timestamps = self._client_operation_history.setdefault(client_id, [])
        known_receivers = self._client_known_receivers.setdefault(client_id, set())

        is_new_receiver = receiver_account_id is not None and receiver_account_id not in known_receivers

        risk_level, reasons = self.risk_analyzer.analyze(
            amount=amount,
            recent_operation_timestamps=timestamps,
            is_new_receiver=is_new_receiver,
        )

        # фиксируем время ЭТОЙ операции для будущих проверок частоты —
        # делаем это после анализа, чтобы сама операция не засчитывалась
        # в свою же собственную статистику "частых операций"
        timestamps.append(self._time_provider())

        if risk_level == RiskLevel.HIGH:
            self.audit_log.record(
                AuditSeverity.CRITICAL, "risk",
                f"Операция заблокирована: {'; '.join(reasons)}",
                client_id=client_id, amount=amount, risk_level=risk_level,
            )
            raise SuspiciousOperationBlockedError(
                f"Операция на сумму {amount} заблокирована как высокорискованная: {'; '.join(reasons)}"
            )

        if risk_level == RiskLevel.MEDIUM:
            self.audit_log.record(
                AuditSeverity.WARNING, "risk",
                f"Операция помечена как подозрительная: {'; '.join(reasons)}",
                client_id=client_id, amount=amount, risk_level=risk_level,
            )
        else:
            self.audit_log.record(
                AuditSeverity.INFO, "risk", "Операция в пределах нормы",
                client_id=client_id, amount=amount, risk_level=risk_level,
            )

        # получателя запоминаем только если операция прошла риск-проверку —
        # так заблокированная попытка перевода не "отбеливает" новый счёт
        if receiver_account_id is not None:
            known_receivers.add(receiver_account_id)

        return risk_level

    def get_suspicious_operations_report(self) -> list:
        """Отчёт: все операции, помеченные как WARNING или CRITICAL."""
        return (
            self.audit_log.filter(severity=AuditSeverity.WARNING)
            + self.audit_log.filter(severity=AuditSeverity.CRITICAL)
        )

    def get_client_risk_profile(self, client_id: str) -> dict:
        """Отчёт: сколько операций клиента получили каждый уровень риска."""
        events = self.audit_log.filter(client_id=client_id, category="risk")
        profile = {"client_id": client_id, "total_operations": len(events), "low": 0, "medium": 0, "high": 0}
        for event in events:
            level = event.details.get("risk_level")
            if level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH):
                profile[level] += 1
        return profile

    @staticmethod
    def get_error_statistics(error_log: list) -> dict:
        """
        Отчёт: статистика ошибок обработки транзакций.
        error_log — это TransactionProcessor.error_log (список словарей
        {"transaction_id", "error", "error_type", "attempt", "timestamp"}).
        Bank намеренно не хранит этот лог сам — это ответственность
        TransactionProcessor, Bank просто помогает свести сырые данные
        в сводку по типам ошибок.
        """
        # Counter — специализированный словарь для подсчёта: Counter(iterable)
        # сам считает, сколько раз встретилось каждое значение
        return dict(Counter(entry.get("error_type", "Unknown") for entry in error_log))
    # === КОНЕЦ НОВОГО ===

    # ---------- работа с клиентами ----------

    def add_client(self, client: Client) -> Client:
        self.clients[client.client_id] = client
        return client

    # ---------- работа со счетами ----------

    def open_account(self, client_id: str, account_type: str = "bank", currency: str = "RUB", **kwargs):
        client = self._get_client(client_id)

        account_cls = ACCOUNT_CLASSES.get(account_type)
        if account_cls is None:
            raise InvalidOperationError(
                f"Неизвестный тип счёта: {account_type}. "
                f"Доступные: {', '.join(ACCOUNT_CLASSES)}"
            )

        # **kwargs — сюда прилетят специфичные для типа счёта параметры
        # (min_balance, monthly_rate для SavingsAccount и т.д.), которые
        # Bank сам не обязан знать заранее — он просто прокидывает их дальше
        account = account_cls(owner=client.full_name, currency=currency, **kwargs)

        account_id = account.get_account_info()["account_id"]
        self.accounts[account_id] = account
        client.account_ids.append(account_id)
        self._account_owners[account_id] = client_id  # === НОВОЕ (День 5) ===
        return account

    def close_account(self, account_id: str):
        account = self._get_account(account_id)
        account.close()
        return account

    def freeze_account(self, account_id: str):
        account = self._get_account(account_id)
        account.freeze()
        return account

    def unfreeze_account(self, account_id: str):
        account = self._get_account(account_id)
        account.unfreeze()
        return account

    # ---------- денежные операции через банк (с ночным ограничением) ----------

    def deposit_to_account(self, account_id: str, amount: float):
        self._check_night_restriction()
        account = self._get_account(account_id)
        return account.deposit(amount)

    def withdraw_from_account(self, account_id: str, client_id: str, amount: float):
        self._check_night_restriction()
        account = self._get_account(account_id)

        if amount > self.SUSPICIOUS_AMOUNT_THRESHOLD:
            self._flag_suspicious(
                client_id,
                f"Крупное снятие: {amount} (порог: {self.SUSPICIOUS_AMOUNT_THRESHOLD})",
            )

        # === НОВОЕ (День 5) ===
        # новая, более полная риск-проверка поверх старой (см. пояснение
        # в чате про то, почему старая система осталась нетронутой).
        # Может бросить SuspiciousOperationBlockedError — тогда снятие
        # не произойдёт вообще (return ниже не выполнится).
        self.check_operation_risk(client_id, amount)
        # === КОНЕЦ НОВОГО ===

        return account.withdraw(amount)

    # ---------- аутентификация ----------

    def authenticate_client(self, client_id: str, password: str) -> bool:
        client = self._get_client(client_id)

        if client.status == ClientStatus.BLOCKED:
            raise ClientBlockedError(f"Клиент {client_id} заблокирован.")

        if not client.verify_password(password):
            attempts = self._login_attempts.get(client_id, 0) + 1
            self._login_attempts[client_id] = attempts

            if attempts >= MAX_LOGIN_ATTEMPTS:
                client.status = ClientStatus.BLOCKED
                self._flag_suspicious(
                    client_id, f"{MAX_LOGIN_ATTEMPTS} неверных попытки входа подряд — клиент заблокирован"
                )
                raise ClientBlockedError(
                    f"Клиент {client_id} заблокирован после {MAX_LOGIN_ATTEMPTS} неверных попыток входа."
                )

            raise AuthenticationError(
                f"Неверный пароль. Попытка {attempts}/{MAX_LOGIN_ATTEMPTS}."
            )

        # успешный вход — сбрасываем счётчик неверных попыток
        self._login_attempts[client_id] = 0
        return True

    # ---------- поиск и статистика ----------

    def search_accounts(self, owner_name: str = None, currency: str = None, account_type: str = None):
        results = []
        for account in self.accounts.values():
            info = account.get_account_info()

            if owner_name is not None and owner_name.lower() not in info["owner"].lower():
                continue
            if currency is not None and info["currency"] != currency:
                continue
            if account_type is not None and info.get("type", "BankAccount") != account_type:
                continue

            results.append(account)
        return results

    def get_total_balance(self) -> dict:
        totals = {}
        for account in self.accounts.values():
            info = account.get_account_info()
            totals[info["currency"]] = totals.get(info["currency"], 0.0) + info["balance"]
        return totals

    def get_clients_ranking(self, currency: str = "RUB") -> list:
        ranking = []
        for client in self.clients.values():
            total = 0.0
            for account_id in client.account_ids:
                account = self.accounts.get(account_id)
                if account is None:
                    continue
                info = account.get_account_info()
                if info["currency"] == currency:
                    total += info["balance"]
            ranking.append((client, total))

        ranking.sort(key=lambda pair: pair[1], reverse=True)
        return ranking


# Функцию demo() ниже я не трогаю — оставь свою версию как есть,
# новая функциональность в неё не встраивается, чтобы не рисковать
# сломать то, чего я не вижу целиком. Хочешь продемонстрировать
# блокировку риска в demo() — просто добавь в конец что-то вроде:
#
#     try:
#         bank.withdraw_from_account(acc1.get_account_info()["account_id"], alice.client_id, 600000)
#     except Exception as e:
#         print(f"Заблокировано риск-анализом: {e}")
