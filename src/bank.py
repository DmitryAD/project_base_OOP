"""Банк: клиенты, счета, аутентификация, контроль рисков и сводная статистика."""

from collections import Counter
from datetime import datetime, time
from decimal import Decimal

from audit import AuditLog, AuditSeverity
from client import Client, ClientStatus
from exceptions import (
    AccountNotFoundError,
    AuthenticationError,
    ClientBlockedError,
    ClientNotFoundError,
    InvalidOperationError,
    NightOperationRestrictedError,
    SuspiciousOperationBlockedError,
)
from main import (
    ZERO,
    BankAccount,
    InvestmentAccount,
    PremiumAccount,
    SavingsAccount,
    default_rate_provider,
    round_money,
    to_decimal,
)
from risk import RiskAnalyzer, RiskLevel

ACCOUNT_CLASSES = {
    "bank": BankAccount,
    "savings": SavingsAccount,
    "premium": PremiumAccount,
    "investment": InvestmentAccount,
}

RISK_SEVERITY = {
    RiskLevel.LOW: AuditSeverity.INFO,
    RiskLevel.MEDIUM: AuditSeverity.WARNING,
    RiskLevel.HIGH: AuditSeverity.CRITICAL,
}


class Bank:
    """Центральный объект системы.

    Хранит клиентов и счета, выполняет операции через единые проверки
    (ночной запрет, принадлежность счёта, оценка риска) и записывает
    значимые события в журнал аудита. Источник времени, сервис курсов,
    журнал и анализатор рисков передаются в конструктор, что позволяет
    подменять их в тестах.
    """

    NIGHT_START = time(0, 0)
    NIGHT_END = time(5, 0)
    MAX_LOGIN_ATTEMPTS = 3

    def __init__(
        self,
        name: str,
        time_provider=datetime.now,
        audit_log: AuditLog | None = None,
        risk_analyzer: RiskAnalyzer | None = None,
        rate_provider=default_rate_provider,
    ):
        self.name = name
        self._time_provider = time_provider
        self._rate_provider = rate_provider
        self.audit_log = audit_log if audit_log is not None else AuditLog(time_provider=time_provider)
        self.risk_analyzer = (
            risk_analyzer if risk_analyzer is not None else RiskAnalyzer(time_provider=time_provider)
        )

        self.clients: dict[str, Client] = {}
        self.accounts: dict[str, BankAccount] = {}
        self._account_owners: dict[str, str] = {}
        self._login_attempts: dict[str, int] = {}
        self._operation_history: dict[str, list[datetime]] = {}
        self._known_receivers: dict[str, set[str]] = {}

    def now(self) -> datetime:
        """Текущее время по часам банка."""
        return self._time_provider()

    def add_client(self, client: Client) -> Client:
        if client.client_id in self.clients:
            raise InvalidOperationError(f"Клиент с ID {client.client_id} уже существует.")
        self.clients[client.client_id] = client
        self.audit_log.record(
            AuditSeverity.INFO, "client", "Клиент зарегистрирован", client_id=client.client_id
        )
        return client

    def get_client(self, client_id: str) -> Client:
        client = self.clients.get(client_id)
        if client is None:
            raise ClientNotFoundError(f"Клиент с ID {client_id} не найден.")
        return client

    def get_account(self, account_id: str) -> BankAccount:
        account = self.accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(f"Счёт с ID {account_id} не найден.")
        return account

    def get_client_id_for_account(self, account_id: str | None) -> str | None:
        return self._account_owners.get(account_id)

    def get_client_accounts(self, client_id: str) -> list[BankAccount]:
        client = self.get_client(client_id)
        return [self.accounts[account_id] for account_id in client.account_ids]

    def open_account(
        self,
        client_id: str,
        account_type: str = "bank",
        currency: str = "RUB",
        **account_options,
    ) -> BankAccount:
        """Открывает счёт; параметры конкретного типа передаются через account_options."""
        client = self.get_client(client_id)
        if client.status == ClientStatus.BLOCKED:
            raise ClientBlockedError(f"Клиент {client_id} заблокирован.")

        account_cls = ACCOUNT_CLASSES.get(account_type)
        if account_cls is None:
            available = ", ".join(ACCOUNT_CLASSES)
            raise InvalidOperationError(
                f"Неизвестный тип счёта: {account_type}. Доступные: {available}."
            )

        account = account_cls(owner=client.full_name, currency=currency, **account_options)
        self.accounts[account.account_id] = account
        self._account_owners[account.account_id] = client_id
        client.account_ids.append(account.account_id)
        self.audit_log.record(
            AuditSeverity.INFO, "account", f"Открыт счёт {account.account_id}",
            client_id=client_id, account_type=account.ACCOUNT_TYPE, currency=currency,
        )
        return account

    def close_account(self, account_id: str) -> BankAccount:
        account = self.get_account(account_id)
        account.close()
        self._record_account_event(account_id, "Счёт закрыт")
        return account

    def freeze_account(self, account_id: str) -> BankAccount:
        account = self.get_account(account_id)
        account.freeze()
        self._record_account_event(account_id, "Счёт заморожен")
        return account

    def unfreeze_account(self, account_id: str) -> BankAccount:
        account = self.get_account(account_id)
        account.unfreeze()
        self._record_account_event(account_id, "Счёт разморожен")
        return account

    def _record_account_event(self, account_id: str, message: str):
        self.audit_log.record(
            AuditSeverity.INFO, "account", f"{message}: {account_id}",
            client_id=self.get_client_id_for_account(account_id),
        )

    def is_night(self) -> bool:
        return self.NIGHT_START <= self.now().time() < self.NIGHT_END

    def check_night_restriction(self):
        if self.is_night():
            raise NightOperationRestrictedError(
                f"Операции недоступны с {self.NIGHT_START:%H:%M} до {self.NIGHT_END:%H:%M}."
            )

    def check_operation_risk(
        self,
        client_id: str,
        amount,
        receiver_account_id: str | None = None,
    ) -> str:
        """Оценивает риск операции клиента и фиксирует результат в журнале.

        Единая точка риск-контроля для прямых операций банка и для
        TransactionProcessor. Возвращает уровень риска для разрешённой
        операции и выбрасывает SuspiciousOperationBlockedError для
        высокорискованной. Время операции добавляется в историю после
        анализа, чтобы операция не учитывалась в собственной частоте.
        Получатель считается известным только после успешной проверки,
        поэтому заблокированная попытка не делает новый счёт доверенным.
        """
        amount = to_decimal(amount)
        now = self.now()
        history = self._operation_history.setdefault(client_id, [])
        known_receivers = self._known_receivers.setdefault(client_id, set())
        is_new_receiver = receiver_account_id is not None and receiver_account_id not in known_receivers

        level, reasons = self.risk_analyzer.analyze(
            amount=amount,
            recent_operation_timestamps=history,
            is_new_receiver=is_new_receiver,
        )

        window = self.risk_analyzer.FREQUENT_OPERATIONS_WINDOW
        history[:] = [ts for ts in history if now - ts <= window]
        history.append(now)

        reason_text = "; ".join(reasons)
        messages = {
            RiskLevel.LOW: "Операция в пределах нормы",
            RiskLevel.MEDIUM: f"Операция помечена как подозрительная: {reason_text}",
            RiskLevel.HIGH: f"Операция заблокирована: {reason_text}",
        }
        self.audit_log.record(
            RISK_SEVERITY[level], "risk", messages[level],
            client_id=client_id, amount=amount, risk_level=level, reasons=reasons,
        )

        if level == RiskLevel.HIGH:
            raise SuspiciousOperationBlockedError(
                f"Операция на сумму {amount} заблокирована как высокорискованная: {reason_text}"
            )

        if receiver_account_id is not None:
            known_receivers.add(receiver_account_id)
        return level

    def deposit_to_account(self, account_id: str, amount) -> Decimal:
        self.check_night_restriction()
        return self.get_account(account_id).deposit(amount)

    def withdraw_from_account(self, account_id: str, client_id: str, amount) -> Decimal:
        self.check_night_restriction()
        account = self.get_account(account_id)
        if self.get_client_id_for_account(account_id) != client_id:
            raise InvalidOperationError(
                f"Счёт {account_id} не принадлежит клиенту {client_id}."
            )
        self.check_operation_risk(client_id, amount)
        return account.withdraw(amount)

    def authenticate_client(self, client_id: str, password: str) -> bool:
        client = self.get_client(client_id)
        if client.status == ClientStatus.BLOCKED:
            raise ClientBlockedError(f"Клиент {client_id} заблокирован.")

        if client.verify_password(password):
            self._login_attempts[client_id] = 0
            self.audit_log.record(AuditSeverity.INFO, "auth", "Успешный вход", client_id=client_id)
            return True

        attempts = self._login_attempts.get(client_id, 0) + 1
        self._login_attempts[client_id] = attempts

        if attempts >= self.MAX_LOGIN_ATTEMPTS:
            client.status = ClientStatus.BLOCKED
            self.audit_log.record(
                AuditSeverity.CRITICAL, "auth",
                f"Клиент заблокирован после {attempts} неверных попыток входа",
                client_id=client_id,
            )
            raise ClientBlockedError(
                f"Клиент {client_id} заблокирован после {attempts} неверных попыток входа."
            )

        self.audit_log.record(
            AuditSeverity.WARNING, "auth", f"Неверный пароль, попытка {attempts}",
            client_id=client_id,
        )
        raise AuthenticationError(
            f"Неверный пароль. Попытка {attempts}/{self.MAX_LOGIN_ATTEMPTS}."
        )

    def search_accounts(
        self,
        owner_name: str | None = None,
        currency: str | None = None,
        account_type: str | None = None,
    ) -> list[BankAccount]:
        return [
            account
            for account in self.accounts.values()
            if (owner_name is None or owner_name.lower() in account.owner.lower())
            and (currency is None or account.currency == currency)
            and (account_type is None or account.ACCOUNT_TYPE == account_type)
        ]

    def get_total_balance(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for account in self.accounts.values():
            totals[account.currency] = totals.get(account.currency, ZERO) + account.balance
        return totals

    def get_client_total_balance(self, client_id: str, currency: str = "RUB") -> Decimal:
        """Суммарный баланс всех счетов клиента в пересчёте на указанную валюту."""
        total = ZERO
        for account in self.get_client_accounts(client_id):
            rate = to_decimal(self._rate_provider(account.currency, currency))
            total += round_money(account.balance * rate)
        return total

    def get_clients_ranking(self, currency: str = "RUB") -> list[tuple[Client, Decimal]]:
        """Клиенты по убыванию суммарного баланса в пересчёте на указанную валюту."""
        ranking = [
            (client, self.get_client_total_balance(client.client_id, currency))
            for client in self.clients.values()
        ]
        ranking.sort(key=lambda pair: pair[1], reverse=True)
        return ranking

    def get_suspicious_operations_report(self) -> list:
        """События уровня WARNING и CRITICAL в хронологическом порядке."""
        suspicious = {AuditSeverity.WARNING, AuditSeverity.CRITICAL}
        return [event for event in self.audit_log.filter() if event.severity in suspicious]

    def get_client_risk_profile(self, client_id: str) -> dict:
        """Количество операций клиента на каждом уровне риска."""
        events = self.audit_log.filter(client_id=client_id, category="risk")
        levels = Counter(event.details.get("risk_level") for event in events)
        return {
            "client_id": client_id,
            "total_operations": len(events),
            RiskLevel.LOW: levels[RiskLevel.LOW],
            RiskLevel.MEDIUM: levels[RiskLevel.MEDIUM],
            RiskLevel.HIGH: levels[RiskLevel.HIGH],
        }

    @staticmethod
    def get_error_statistics(error_log: list[dict]) -> dict[str, int]:
        """Число ошибок обработки транзакций по типам исключений."""
        return dict(Counter(entry.get("error_type", "Unknown") for entry in error_log))