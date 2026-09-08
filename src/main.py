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
        return str(uuid.uuid4())[:8].upper()

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

    def __init__(self, owner: str, currency: str = "RUB", account_id: str = None):
        super().__init__(owner, account_id)

        if not owner or not isinstance(owner, str):
            raise InvalidOperationError("Некорректные данные владельца счёта.")

        if currency not in self.ALLOWED_CURRENCIES:
            raise InvalidOperationError(
                f"Неподдерживаемая валюта: {currency}. "
                f"Допустимые: {', '.join(self.ALLOWED_CURRENCIES)}"
            )

        self.currency = currency

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

    def deposit(self, amount: float):
        self._check_status_for_operation()
        self._validate_amount(amount)
        self._balance += amount
        return self._balance

    def withdraw(self, amount: float):
        self._check_status_for_operation()
        self._validate_amount(amount)
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
        }

    def __str__(self):
        last4 = self._account_id[-4:]
        return (
            f"BankAccount | Клиент: {self._owner} | "
            f"№ ****{last4} | Статус: {self._status} | "
            f"Баланс: {self._balance:.2f} {self.currency}"
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

    print("Попытка снять больше, чем есть на счёте:")
    try:
        acc1.withdraw(999999)
    except InsufficientFundsError as e:
        print(f"Ошибка: {e}")


if __name__ == "__main__":
    demo()
