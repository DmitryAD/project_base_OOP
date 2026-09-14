import uuid
from abc import ABC, abstractmethod

from exceptions import (
    AccountFrozenError,
    AccountClosedError,
    InvalidOperationError,
    InsufficientFundsError,
)


class AccountStatus:
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class AbstractAccount(ABC):
    """Абстрактная базовая модель банковского счёта."""

    def __init__(self, owner: str, account_id: str = None):
        self._account_id = account_id or self._generate_id()
        self._owner = owner
        self._balance = 0.0
        self._status = AccountStatus.ACTIVE

    @staticmethod
    def _generate_id() -> str:
        return str(uuid.uuid4().int)[:8]

    @abstractmethod
    def deposit(self, amount: float):
        ...

    @abstractmethod
    def withdraw(self, amount: float):
        ...

    @abstractmethod
    def get_account_info(self) -> dict:
        ...


class BankAccount(AbstractAccount):
    """Конкретная реализация банковского счёта."""

    ALLOWED_CURRENCIES = {"RUB", "USD", "EUR", "KZT", "CNY"}

    def __init__(
        self,
        owner: str,
        currency: str = "RUB",
        account_id: str = None,
        max_transaction_limit: float = 100_000.0,  # === НОВОЕ ===
    ):
        super().__init__(owner, account_id)

        if not owner or not isinstance(owner, str):
            raise InvalidOperationError("Некорректные данные владельца счёта.")

        if currency not in self.ALLOWED_CURRENCIES:
            raise InvalidOperationError(
                f"Неподдерживаемая валюта: {currency}. "
                f"Допустимые: {', '.join(self.ALLOWED_CURRENCIES)}"
            )

        self.currency = currency
        self.max_transaction_limit = max_transaction_limit  # === НОВОЕ ===

    def _check_status_for_operation(self):
        if self._status == AccountStatus.FROZEN:
            raise AccountFrozenError(f"Счёт {self._account_id} заморожен.")
        if self._status == AccountStatus.CLOSED:
            raise AccountClosedError(f"Счёт {self._account_id} закрыт.")

    @staticmethod
    def _validate_amount(amount):
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise InvalidOperationError("Сумма должна быть числом.")
        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть положительной.")

    # === НОВОЕ ===
    def _check_transaction_limit(self, amount):
        # это НЕ @staticmethod, в отличие от _validate_amount, потому что
        # лимит теперь свой у каждого объекта (self.max_transaction_limit),
        # а не общий для всех — значит, методу нужен доступ к self
        if amount > self.max_transaction_limit:
            raise InvalidOperationError(
                f"Сумма операции {amount} {self.currency} превышает "
                f"максимально разрешённую ({self.max_transaction_limit} {self.currency})."
            )
    # === КОНЕЦ НОВОГО ===

    def deposit(self, amount: float):
        self._check_status_for_operation()
        self._validate_amount(amount)
        self._check_transaction_limit(amount)  # === НОВОЕ ===
        self._balance += amount
        return self._balance

    def withdraw(self, amount: float):
        self._check_status_for_operation()
        self._validate_amount(amount)
        self._check_transaction_limit(amount)  # === НОВОЕ ===
        if amount > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно средств: на счёте {self._balance} {self.currency}."
            )
        self._balance -= amount
        return self._balance

    def freeze(self):
        self._status = AccountStatus.FROZEN

    def unfreeze(self):
        if self._status != AccountStatus.CLOSED:
            self._status = AccountStatus.ACTIVE

    def close(self):
        self._status = AccountStatus.CLOSED

    def get_account_info(self) -> dict:
        return {
            "account_id": self._account_id,
            "owner": self._owner,
            "status": self._status,
            "balance": self._balance,
            "currency": self.currency,
            "max_transaction_limit": self.max_transaction_limit,  # === НОВОЕ ===
        }

    def __str__(self):
        last4 = self._account_id[-4:]
        return (
            f"BankAccount | Клиент: {self._owner} | "
            f"№ ****{last4} | Статус: {self._status} | "
            f"Баланс: {self._balance:.2f} {self.currency}"
        )


class SavingsAccount(BankAccount):
    """Накопительный счёт: нельзя уходить ниже минимального остатка,
    можно начислять проценты раз в месяц."""

    def __init__(
        self,
        owner: str,
        currency: str = "RUB",
        account_id: str = None,
        min_balance: float = 1000.0,
        monthly_rate: float = 0.03,
    ):
        super().__init__(owner, currency, account_id)
        self.min_balance = min_balance
        self.monthly_rate = monthly_rate

    def withdraw(self, amount: float):
        self._check_status_for_operation()
        self._validate_amount(amount)
        self._check_transaction_limit(amount)  # === НОВОЕ ===

        if self._balance - amount < self.min_balance:
            raise InsufficientFundsError(
                f"Нельзя снять {amount} {self.currency}: баланс не может "
                f"опуститься ниже минимального остатка {self.min_balance} {self.currency}."
            )

        self._balance -= amount
        return self._balance

    def apply_monthly_interest(self):
        self._check_status_for_operation()
        interest = self._balance * self.monthly_rate
        self._balance += interest
        return interest

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info.update({
            "type": "SavingsAccount",
            "min_balance": self.min_balance,
            "monthly_rate": self.monthly_rate,
        })
        return info

    def __str__(self):
        last4 = self._account_id[-4:]
        return (
            f"SavingsAccount | Клиент: {self._owner} | № ****{last4} | "
            f"Статус: {self._status} | Баланс: {self._balance:.2f} {self.currency} | "
            f"Мин. остаток: {self.min_balance:.2f} | Ставка: {self.monthly_rate * 100:.1f}%/мес"
        )


class PremiumAccount(BankAccount):
    """Премиальный счёт: увеличенный лимит на операцию, разрешён овердрафт
    (уход в минус до лимита), каждое снятие облагается фиксированной комиссией."""

    def __init__(
        self,
        owner: str,
        currency: str = "RUB",
        account_id: str = None,
        overdraft_limit: float = 50000.0,
        withdrawal_fee: float = 50.0,
        max_transaction_limit: float = 1_000_000.0,  # === НОВОЕ: выше, чем у BankAccount (100_000) ===
    ):
        # === ИЗМЕНЕНО: теперь передаём свой max_transaction_limit родителю ===
        super().__init__(owner, currency, account_id, max_transaction_limit=max_transaction_limit)
        self.overdraft_limit = overdraft_limit
        self.withdrawal_fee = withdrawal_fee

    def withdraw(self, amount: float):
        self._check_status_for_operation()
        self._validate_amount(amount)
        self._check_transaction_limit(amount)  # === НОВОЕ ===

        total_deduction = amount + self.withdrawal_fee
        if self._balance - total_deduction < -self.overdraft_limit:
            raise InsufficientFundsError(
                f"Превышен лимит овердрафта ({self.overdraft_limit} {self.currency}) "
                f"с учётом комиссии {self.withdrawal_fee} {self.currency}."
            )

        self._balance -= total_deduction
        return self._balance

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info.update({
            "type": "PremiumAccount",
            "overdraft_limit": self.overdraft_limit,
            "withdrawal_fee": self.withdrawal_fee,
        })
        return info

    def __str__(self):
        last4 = self._account_id[-4:]
        return (
            f"PremiumAccount | Клиент: {self._owner} | № ****{last4} | "
            f"Статус: {self._status} | Баланс: {self._balance:.2f} {self.currency} | "
            f"Овердрафт до: {self.overdraft_limit:.2f} | Комиссия за снятие: {self.withdrawal_fee:.2f} | "
            f"Лимит на операцию: {self.max_transaction_limit:.2f}"
        )


class InvestmentAccount(BankAccount):
    """Инвестиционный счёт: часть денег можно 'вложить' в активы
    (акции, облигации, ETF) — это отдельно от свободного баланса."""

    ASSET_YEARLY_RETURN = {"stocks": 0.10, "bonds": 0.04, "etf": 0.07}

    def __init__(self, owner: str, currency: str = "RUB", account_id: str = None):
        super().__init__(owner, currency, account_id)
        self.portfolio = {"stocks": 0.0, "bonds": 0.0, "etf": 0.0}

    def buy_asset(self, asset_type: str, amount: float):
        if asset_type not in self.portfolio:
            raise InvalidOperationError(f"Неизвестный тип актива: {asset_type}")

        self._check_status_for_operation()
        self._validate_amount(amount)
        self._check_transaction_limit(amount)  # === НОВОЕ ===

        if amount > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно свободных средств для покупки {asset_type}."
            )

        self._balance -= amount
        self.portfolio[asset_type] += amount
        return self.portfolio

    def withdraw(self, amount: float):
        self._check_status_for_operation()
        self._validate_amount(amount)
        self._check_transaction_limit(amount)  # === НОВОЕ ===

        if amount > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно свободных средств: {self._balance:.2f} {self.currency} "
                f"(деньги в портфеле не учитываются)."
            )

        self._balance -= amount
        return self._balance

    def project_yearly_growth(self) -> dict:
        projected = {
            asset: value * (1 + self.ASSET_YEARLY_RETURN[asset])
            for asset, value in self.portfolio.items()
        }
        return projected

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info.update({
            "type": "InvestmentAccount",
            "portfolio": self.portfolio,
        })
        return info

    def __str__(self):
        last4 = self._account_id[-4:]
        portfolio_str = ", ".join(f"{k}: {v:.2f}" for k, v in self.portfolio.items())
        return (
            f"InvestmentAccount | Клиент: {self._owner} | № ****{last4} | "
            f"Статус: {self._status} | Своб. баланс: {self._balance:.2f} {self.currency} | "
            f"Портфель: [{portfolio_str}]"
        )


def demo():
    print("=== Демонстрация работы BankAccount ===\n")

    acc1 = BankAccount(owner="Иван Иванов", currency="RUB")
    print("Создан активный счёт:")
    print(acc1, "\n")

    acc2 = BankAccount(owner="Мария Петрова", currency="USD")
    acc2.freeze()
    print("Создан и заморожен счёт:")
    print(acc2, "\n")

    print("Попытка операций над замороженным счётом:")
    try:
        acc2.deposit(100)
    except AccountFrozenError as e:
        print(f"Ошибка: {e}")

    try:
        acc2.withdraw(50)
    except AccountFrozenError as e:
        print(f"Ошибка: {e}\n")

    print("Валидное пополнение и снятие на активном счёте:")
    acc1.deposit(1000)
    print(f"После пополнения на 1000: {acc1}")

    acc1.withdraw(300)
    print(f"После снятия 300: {acc1}\n")

    # print("Попытка снять больше, чем есть на счёте:")
    # try:
    #     acc1.withdraw(999999)
    # except InsufficientFundsError as e:
    #     print(f"Ошибка: {e}")

    print("\n=== Демонстрация дочерних классов (День 2) ===\n")

    savings = SavingsAccount(owner="Анна Смирнова", currency="RUB", min_balance=1000, monthly_rate=0.03)
    savings.deposit(5000)
    print("Накопительный счёт после пополнения на 5000:")
    print(savings)

    try:
        savings.withdraw(4500)  # оставит 500 — ниже min_balance=1000
    except InsufficientFundsError as e:
        print(f"Ошибка при снятии: {e}")

    interest = savings.apply_monthly_interest()
    print(f"Начислены проценты: {interest:.2f}")
    print(savings, "\n")

    premium = PremiumAccount(owner="Олег Кузнецов", currency="USD", overdraft_limit=1000, withdrawal_fee=10)
    premium.deposit(200)
    premium.withdraw(500)  # уйдёт в минус за счёт овердрафта — это разрешено
    print("Премиальный счёт после снятия с овердрафтом:")
    print(premium, "\n")

    # === НОВОЕ: демонстрация лимита на операцию ===
    print("Попытка превысить лимит на операцию у обычного BankAccount:")
    try:
        acc1.deposit(200_000)  # лимит по умолчанию — 100_000
    except InvalidOperationError as e:
        print(f"Ошибка: {e}\n")
    # === КОНЕЦ НОВОГО ===

    invest = InvestmentAccount(owner="Мария Петрова", currency="RUB")
    invest.deposit(10000)
    invest.buy_asset("stocks", 4000)
    invest.buy_asset("bonds", 2000)
    print("Инвестиционный счёт после покупки активов:")
    print(invest)

    growth = invest.project_yearly_growth()
    print(f"Прогноз портфеля через год: {growth}")


if __name__ == "__main__":
    demo()
