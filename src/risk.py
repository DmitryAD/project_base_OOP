"""Оценка риска отдельной операции по набору правил."""

from datetime import datetime, timedelta
from decimal import Decimal


class RiskLevel:
    """Уровни риска операции."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskAnalyzer:
    """Оценивает риск операции по четырём признакам.

    Признаки: крупная сумма, частые операции, перевод на новый счёт,ночное время.
    Уровень определяется числом сработавших признаков: 0 — низкий, 1 — средний, 2 и более — высокий.

    Анализатор не хранит состояние клиентов: история операций и сведения о получателе передаются в analyze().
    Поэтому его можно использовать и тестировать отдельно от Bank.
    Сам Bank запрещает операции ночью до вызова анализатора, так что внутри банка ночной признак служит дополнительной защитой для политик без жёсткого запрета.
    """

    LARGE_AMOUNT_THRESHOLD = Decimal("500000")
    FREQUENT_OPERATIONS_WINDOW = timedelta(minutes=10)
    FREQUENT_OPERATIONS_THRESHOLD = 5
    NIGHT_START_HOUR = 0
    NIGHT_END_HOUR = 5

    def __init__(self, time_provider=datetime.now):
        self._time_provider = time_provider

    def analyze(
        self,
        amount,
        recent_operation_timestamps: list[datetime],
        is_new_receiver: bool,
    ) -> tuple[str, list[str]]:
        """Возвращает уровень риска и список причин, по которым он назначен."""
        now = self._time_provider()
        reasons = []

        if amount > self.LARGE_AMOUNT_THRESHOLD:
            reasons.append(f"крупная сумма операции: {amount}")

        recent_count = self.count_recent(recent_operation_timestamps, now)
        if recent_count >= self.FREQUENT_OPERATIONS_THRESHOLD:
            minutes = int(self.FREQUENT_OPERATIONS_WINDOW.total_seconds() // 60)
            reasons.append(f"частые операции: {recent_count} за последние {minutes} мин.")

        if is_new_receiver:
            reasons.append("перевод на новый (ранее не встречавшийся) счёт")

        if self.NIGHT_START_HOUR <= now.hour < self.NIGHT_END_HOUR:
            reasons.append("операция в ночное время")

        return self._determine_level(reasons), reasons

    def count_recent(self, timestamps: list[datetime], now: datetime) -> int:
        """Считает операции, попадающие в окно частоты относительно now."""
        return sum(1 for ts in timestamps if now - ts <= self.FREQUENT_OPERATIONS_WINDOW)

    @staticmethod
    def _determine_level(reasons: list[str]) -> str:
        if len(reasons) >= 2:
            return RiskLevel.HIGH
        if len(reasons) == 1:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
