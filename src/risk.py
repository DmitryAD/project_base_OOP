"""
Модуль анализа рисков: оценивает одну операцию в контексте истории
клиента и присваивает ей уровень риска.
"""

from datetime import datetime, timedelta


class RiskLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskAnalyzer:
    """
    Не хранит состояние клиентов сам — принимает историю операций и
    список известных получателей аргументами в analyze(). Так его легко
    тестировать в изоляции (без Bank) и переиспользовать где угодно.
    """

    LARGE_AMOUNT_THRESHOLD = 500_000.0
    FREQUENT_OPERATIONS_WINDOW = timedelta(minutes=10)
    FREQUENT_OPERATIONS_THRESHOLD = 5
    NIGHT_START_HOUR = 0
    NIGHT_END_HOUR = 5

    def __init__(self, time_provider=datetime.now):
        # тот же приём dependency injection, что и в Bank/TransactionProcessor —
        # в тестах подставим функцию, которая всегда возвращает, например,
        # 2 часа ночи, и проверим ночной признак в любое время суток
        self._time_provider = time_provider

    def analyze(self, amount: float, recent_operation_timestamps: list, is_new_receiver: bool) -> tuple:
        """
        Возвращает (risk_level, reasons) — reasons это список строк-причин,
        пригодится и для аудита, и для отчётов клиенту/службе безопасности.
        """
        reasons = []
        now = self._time_provider()

        if amount > self.LARGE_AMOUNT_THRESHOLD:
            reasons.append(f"крупная сумма операции: {amount}")

        # считаем, сколько операций клиент совершил в последнее "окно"
        # времени (по умолчанию 10 минут) — это и есть проверка на
        # "частые операции"
        recent_count = sum(
            1 for ts in recent_operation_timestamps
            if now - ts <= self.FREQUENT_OPERATIONS_WINDOW
        )
        if recent_count >= self.FREQUENT_OPERATIONS_THRESHOLD:
            window_minutes = self.FREQUENT_OPERATIONS_WINDOW.seconds // 60
            reasons.append(f"частые операции: {recent_count} за последние {window_minutes} мин.")

        if is_new_receiver:
            reasons.append("перевод на новый (ранее не встречавшийся) счёт")

        if self.NIGHT_START_HOUR <= now.hour < self.NIGHT_END_HOUR:
            reasons.append("операция в ночное время")

        risk_level = self._determine_level(reasons)
        return risk_level, reasons

    @staticmethod
    def _determine_level(reasons: list) -> str:
        """
        Правило: 0 признаков — низкий риск, 1 признак — средний,
        2 и более одновременно — высокий. Чем больше независимых сигналов
        совпало на одной операции, тем меньше это похоже на совпадение.
        """
        if len(reasons) >= 2:
            return RiskLevel.HIGH
        if len(reasons) == 1:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
