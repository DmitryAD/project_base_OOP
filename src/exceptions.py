"""Исключения банковской системы."""


class BankError(Exception):
    """Базовый класс для всех ошибок банковской системы."""


class InvalidOperationError(BankError):
    """Некорректная операция или некорректные входные данные."""


class AccountFrozenError(BankError):
    """Операция запрещена: счёт заморожен."""


class AccountClosedError(BankError):
    """Операция запрещена: счёт закрыт."""


class InsufficientFundsError(BankError):
    """Недостаточно средств для списания."""


class AccountNotFoundError(BankError):
    """Счёт с указанным идентификатором не найден."""


class ClientNotFoundError(BankError):
    """Клиент с указанным идентификатором не найден."""


class UnderageClientError(BankError):
    """Клиент младше минимально допустимого возраста."""


class AuthenticationError(BankError):
    """Неверные учётные данные."""


class ClientBlockedError(BankError):
    """Клиент заблокирован после превышения числа попыток входа."""


class NightOperationRestrictedError(BankError):
    """Операции запрещены в ночное время."""


class SuspiciousOperationBlockedError(BankError):
    """Операция заблокирована как высокорискованная.

    Состояние счёта при этом корректно: решение принято на основе
    оценки риска, а не из-за статуса счёта или нехватки средств.
    """


class CurrencyConversionError(BankError):
    """Временная ошибка получения курса валют; операцию можно повторить."""


class TransactionNotFoundError(BankError):
    """Транзакция с указанным идентификатором не найдена в очереди."""
