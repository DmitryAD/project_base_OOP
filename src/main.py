""" Банковские счета и работа с денежными суммами """

import uuid
from abc import ABC, abstractmethod
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from exceptions import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)


CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def to_decimal(value) -> Decimal:
    """Преобразует число в Decimal.

    float переводится через str(), чтобы получить ожидаемое десятичное значение, а не точную копию двоичной погрешности:
    Decimal(0.1) равен 0.1000000000000000055..., а Decimal("0.1") — ровно 0.1. bool отклоняется явно, так как в Python это подкласс int.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise InvalidOperationError(f"Ожидалось число, получено: {value!r}.")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        raise InvalidOperationError(f"Некорректное число: {value!r}.") from None
    if not result.is_finite():
        raise InvalidOperationError(f"Число должно быть конечным: {value!r}.")
    return result


def round_money(value: Decimal) -> Decimal:
    """Округляет сумму до копеек; половина округляется от нуля."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class AccountStatus:
    """Допустимые статусы счёта."""

    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class AbstractAccount(ABC):
    """Общий контракт счёта: идентификатор, владелец, баланс и статус."""

    def __init__(self, owner: str, account_id: str | None = None):
        if not isinstance(owner, str) or not owner.strip():
            raise InvalidOperationError("Некорректные данные владельца счёта.")
        self._account_id = account_id or self._generate_id()
        self._owner = owner
        self._balance = ZERO
        self._status = AccountStatus.ACTIVE

    @staticmethod
    def _generate_id() -> str:
        return uuid.uuid4().hex[:8]

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def balance(self) -> Decimal:
        return self._balance

    @property
    def status(self) -> str:
        return self._status

    @abstractmethod
    def deposit(self, amount) -> Decimal:
        """Зачисляет сумму на счёт и возвращает новый баланс."""

    @abstractmethod
    def withdraw(self, amount) -> Decimal:
        """Списывает сумму со счёта и возвращает новый баланс."""

    @abstractmethod
    def get_account_info(self) -> dict:
        """Возвращает сведения о счёте в виде словаря."""


class BankAccount(AbstractAccount):
    """Расчётный счёт в одной из поддерживаемых валют с лимитом на операцию."""

    ACCOUNT_TYPE = "BankAccount"
    ALLOWED_CURRENCIES = frozenset({"RUB", "USD", "EUR", "KZT", "CNY"})
    DEFAULT_TRANSACTION_LIMIT = Decimal("100000")

    def __init__(
        self,
        owner: str,
        currency: str = "RUB",
        account_id: str | None = None,
        max_transaction_limit=None,
    ):
        super().__init__(owner, account_id)
        if currency not in self.ALLOWED_CURRENCIES:
            allowed = ", ".join(sorted(self.ALLOWED_CURRENCIES))
            raise InvalidOperationError(
                f"Неподдерживаемая валюта: {currency}. Допустимые: {allowed}."
            )
        if max_transaction_limit is None:
            limit = self.DEFAULT_TRANSACTION_LIMIT
        else:
            limit = to_decimal(max_transaction_limit)
        if limit <= 0:
            raise InvalidOperationError("Лимит на операцию должен быть положительным.")
        self._currency = currency
        self.max_transaction_limit = limit

    @property
    def currency(self) -> str:
        return self._currency

    def _ensure_active(self):
        if self._status == AccountStatus.FROZEN:
            raise AccountFrozenError(f"Счёт {self._account_id} заморожен.")
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Счёт {self._account_id} закрыт.")

    def _prepare_operation(self, amount) -> Decimal:
        """Проверяет статус счёта, сумму и лимит; возвращает сумму в Decimal."""
        self._ensure_active()
        value = round_money(to_decimal(amount))
        if value <= 0:
            raise InvalidOperationError("Сумма должна быть положительной.")
        if value > self.max_transaction_limit:
            raise InvalidOperationError(
                f"Сумма операции {value} {self._currency} превышает "
                f"лимит {self.max_transaction_limit} {self._currency}."
            )
        return value

    def validate_deposit(self, amount) -> Decimal:
        """Проверяет возможность зачисления, не изменяя баланс.

        Используется перед переводом, чтобы убедиться, что получатель
        примет деньги, до того как они будут списаны у отправителя.
        """
        return self._prepare_operation(amount)

    def deposit(self, amount) -> Decimal:
        value = self.validate_deposit(amount)
        self._balance += value
        return self._balance

    def withdraw(self, amount) -> Decimal:
        value = self._prepare_operation(amount)
        if value > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно средств: на счёте {self._balance} {self._currency}."
            )
        self._balance -= value
        return self._balance

    def freeze(self):
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Счёт {self._account_id} закрыт и не может быть заморожен.")
        self._status = AccountStatus.FROZEN

    def unfreeze(self):
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Счёт {self._account_id} закрыт и не может быть разморожен.")
        self._status = AccountStatus.ACTIVE

    def close(self):
        self._status = AccountStatus.CLOSED

    def get_account_info(self) -> dict:
        return {
            "account_id": self._account_id,
            "type": self.ACCOUNT_TYPE,
            "owner": self._owner,
            "status": self._status,
            "balance": self._balance,
            "currency": self._currency,
            "max_transaction_limit": self.max_transaction_limit,
        }

    def __str__(self) -> str:
        return (
            f"{self.ACCOUNT_TYPE} | Клиент: {self._owner} | "
            f"№ ****{self._account_id[-4:]} | Статус: {self._status} | "
            f"Баланс: {self._balance:.2f} {self._currency}"
        )


class SavingsAccount(BankAccount):
    """Накопительный счёт с неснижаемым остатком и ежемесячными процентами."""

    ACCOUNT_TYPE = "SavingsAccount"

    def __init__(
        self,
        owner: str,
        currency: str = "RUB",
        account_id: str | None = None,
        min_balance=1000,
        monthly_rate=0.03,
        max_transaction_limit=None,
    ):
        super().__init__(owner, currency, account_id, max_transaction_limit)
        self.min_balance = to_decimal(min_balance)
        self.monthly_rate = to_decimal(monthly_rate)
        if self.min_balance < 0:
            raise InvalidOperationError("Минимальный остаток не может быть отрицательным.")
        if self.monthly_rate < 0:
            raise InvalidOperationError("Ставка не может быть отрицательной.")

    def withdraw(self, amount) -> Decimal:
        value = self._prepare_operation(amount)
        if self._balance - value < self.min_balance:
            raise InsufficientFundsError(
                f"Нельзя снять {value} {self._currency}: баланс не может опуститься "
                f"ниже минимального остатка {self.min_balance} {self._currency}."
            )
        self._balance -= value
        return self._balance

    def apply_monthly_interest(self) -> Decimal:
        """Начисляет проценты за месяц и возвращает сумму начисления."""
        self._ensure_active()
        interest = round_money(self._balance * self.monthly_rate)
        self._balance += interest
        return interest

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info.update({
            "min_balance": self.min_balance,
            "monthly_rate": self.monthly_rate,
        })
        return info

    def __str__(self) -> str:
        return (
            f"{super().__str__()} | Мин. остаток: {self.min_balance:.2f} | "
            f"Ставка: {self.monthly_rate * 100:.1f}%/мес"
        )


class PremiumAccount(BankAccount):
    """Премиальный счёт: повышенный лимит, овердрафт и комиссия за снятие."""

    ACCOUNT_TYPE = "PremiumAccount"
    DEFAULT_TRANSACTION_LIMIT = Decimal("1000000")

    def __init__(
        self,
        owner: str,
        currency: str = "RUB",
        account_id: str | None = None,
        overdraft_limit=50000,
        withdrawal_fee=50,
        max_transaction_limit=None,
    ):
        super().__init__(owner, currency, account_id, max_transaction_limit)
        self.overdraft_limit = to_decimal(overdraft_limit)
        self.withdrawal_fee = to_decimal(withdrawal_fee)
        if self.overdraft_limit < 0 or self.withdrawal_fee < 0:
            raise InvalidOperationError("Овердрафт и комиссия не могут быть отрицательными.")

    def withdraw(self, amount) -> Decimal:
        value = self._prepare_operation(amount)
        total = value + self.withdrawal_fee
        if self._balance - total < -self.overdraft_limit:
            raise InsufficientFundsError(
                f"Превышен лимит овердрафта {self.overdraft_limit} {self._currency} "
                f"с учётом комиссии {self.withdrawal_fee} {self._currency}."
            )
        self._balance -= total
        return self._balance

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info.update({
            "overdraft_limit": self.overdraft_limit,
            "withdrawal_fee": self.withdrawal_fee,
        })
        return info

    def __str__(self) -> str:
        return (
            f"{super().__str__()} | Овердрафт до: {self.overdraft_limit:.2f} | "
            f"Комиссия за снятие: {self.withdrawal_fee:.2f} | "
            f"Лимит на операцию: {self.max_transaction_limit:.2f}"
        )


class InvestmentAccount(BankAccount):
    """Инвестиционный счёт: свободный баланс и портфель виртуальных активов.

    Средства, вложенные в активы, не входят в свободный баланс и
    недоступны для снятия.
    """

    ACCOUNT_TYPE = "InvestmentAccount"
    ASSET_YEARLY_RETURN = {
        "stocks": Decimal("0.10"),
        "bonds": Decimal("0.04"),
        "etf": Decimal("0.07"),
    }

    def __init__(
        self,
        owner: str,
        currency: str = "RUB",
        account_id: str | None = None,
        max_transaction_limit=None,
    ):
        super().__init__(owner, currency, account_id, max_transaction_limit)
        self._portfolio = {asset: ZERO for asset in self.ASSET_YEARLY_RETURN}

    @property
    def portfolio(self) -> dict:
        """Копия портфеля: изменить активы можно только через buy_asset()."""
        return dict(self._portfolio)

    def buy_asset(self, asset_type: str, amount) -> dict:
        if asset_type not in self._portfolio:
            raise InvalidOperationError(f"Неизвестный тип актива: {asset_type}.")
        value = self._prepare_operation(amount)
        if value > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно свободных средств для покупки {asset_type}."
            )
        self._balance -= value
        self._portfolio[asset_type] += value
        return self.portfolio

    def withdraw(self, amount) -> Decimal:
        value = self._prepare_operation(amount)
        if value > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно свободных средств: {self._balance} {self._currency} "
                f"(средства в портфеле не учитываются)."
            )
        self._balance -= value
        return self._balance

    def project_yearly_growth(self) -> dict:
        """Прогноз стоимости каждого актива через год по ожидаемой доходности."""
        return {
            asset: round_money(value * (1 + self.ASSET_YEARLY_RETURN[asset]))
            for asset, value in self._portfolio.items()
        }

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info["portfolio"] = self.portfolio
        return info

    def __str__(self) -> str:
        portfolio = ", ".join(f"{asset}: {value:.2f}" for asset, value in self._portfolio.items())
        return f"{super().__str__()} | Портфель: [{portfolio}]"
