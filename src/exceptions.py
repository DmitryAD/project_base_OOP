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
