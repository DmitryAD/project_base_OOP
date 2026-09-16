class AccountFrozenError(Exception):
    """Операция запрещена: счёт заморожен."""
    pass


class AccountClosedError(Exception):
    """Операция запрещена: счёт закрыт."""
    pass


class InvalidOperationError(Exception):
    """Некорректная операция (например, неверная сумма)."""
    pass


class InsufficientFundsError(Exception):
    """Недостаточно средств для снятия."""
    pass


class UnderageClientError(Exception):
    """Клиенту меньше минимально разрешённого возраста."""
    pass


class ClientNotFoundError(Exception):
    """Клиент с таким ID не найден в банке."""
    pass


class AccountNotFoundError(Exception):
    """Счёт с таким ID не найден в банке."""
    pass


class AuthenticationError(Exception):
    """Неверный пароль при попытке входа."""
    pass


class ClientBlockedError(Exception):
    """Клиент заблокирован (после 3 неверных попыток входа)."""
    pass


class NightOperationRestrictedError(Exception):
    """Операции запрещены в период с 00:00 до 05:00."""
    pass


class CurrencyConversionError(Exception):
    """Не удалось получить курс конвертации между валютами."""
    pass


class TransactionNotFoundError(Exception):
    """Транзакция с таким ID не найдена в очереди."""
    pass
