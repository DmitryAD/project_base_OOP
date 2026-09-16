from datetime import datetime, time

from client import Client, ClientStatus
from main import BankAccount, SavingsAccount, PremiumAccount, InvestmentAccount
from exceptions import (
    InvalidOperationError,
    ClientNotFoundError,
    AccountNotFoundError,
    AuthenticationError,
    ClientBlockedError,
    NightOperationRestrictedError,
)

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

    def __init__(self, name: str, time_provider=datetime.now):
        # === НОВОЕ: dependency injection через time_provider ===
        # time_provider — это функция (по умолчанию datetime.now, но БЕЗ
        # круглых скобок — мы передаём саму функцию как объект, а не
        # результат её вызова). Внутри Bank мы будем вызывать
        # self._time_provider() каждый раз, когда нужно "текущее время".
        # Зачем: если бы код был жёстко завязан на datetime.now(), ночное
        # ограничение можно было бы протестировать только ночью. А так в
        # тестах мы подставим свою функцию, которая всегда возвращает,
        # например, 2 часа ночи — и проверим ограничение в любое время суток.
        self.name = name
        self._time_provider = time_provider

        self.clients: dict[str, Client] = {}     # client_id -> Client
        self.accounts: dict[str, object] = {}     # account_id -> объект счёта (любого из 4 типов)
        self._login_attempts: dict[str, int] = {}  # client_id -> счётчик неверных попыток входа
        self.suspicious_log: list[dict] = []       # список зафиксированных подозрительных событий

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
    например, TransactionProcessor. Различие между "приватным" и
    "публичным" интерфейсом класса — это явное обозначение того, что
    можно вызывать извне, а что является внутренней реализацией,
    которая может измениться без предупреждения.
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
        # суммировать разные валюты напрямую нельзя (100 USD + 100 RUB —
        # это не 200 чего-либо осмысленного), поэтому считаем отдельно
        # по каждой валюте и возвращаем словарь {валюта: сумма}
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

        # sort(key=...) — сортировка по вычисляемому ключу, а не по самому
        # элементу напрямую. lambda pair: pair[1] — это анонимная функция
        # (без def и без имени), которая принимает один элемент списка
        # (кортеж (client, total)) и возвращает pair[1] — то есть total.
        # Так list.sort понимает: "сортируй кортежи по их второму элементу".
        # reverse=True — по убыванию (сначала самые богатые клиенты)
        ranking.sort(key=lambda pair: pair[1], reverse=True)
        return ranking


def demo():
    from datetime import date

    print("=== Демонстрация системы Bank (День 3) ===\n")

    bank = Bank(name="PyBank")

    # --- клиенты ---
    alice = bank.add_client(Client(
        full_name="Алина Волкова",
        birth_date=date(1995, 6, 20),
        phone="+79990000001",
        email="alina@example.com",
        password="qwerty",
    ))
    print(alice)

    try:
        Client(full_name="Малолетний Клиент", birth_date=date(2015, 1, 1))
    except Exception as e:
        print(f"Ошибка при создании клиента: {e}")

    # --- открытие счетов ---
    acc1 = bank.open_account(alice.client_id, account_type="bank", currency="RUB")
    acc2 = bank.open_account(
        alice.client_id, account_type="savings", currency="RUB",
        min_balance=1000, monthly_rate=0.03,
    )
    print(f"\nОткрыты счета клиента {alice.full_name}: {acc1.get_account_info()['account_id']}, "
          f"{acc2.get_account_info()['account_id']}")

    bank.deposit_to_account(acc1.get_account_info()["account_id"], 10000)
    bank.deposit_to_account(acc2.get_account_info()["account_id"], 5000)

    # --- аутентификация: неверный пароль, потом верный ---
    print("\nПопытка входа с неверным паролем:")
    try:
        bank.authenticate_client(alice.client_id, "wrong-password")
    except Exception as e:
        print(f"Ошибка: {e}")

    print("Успешный вход с верным паролем:")
    ok = bank.authenticate_client(alice.client_id, "qwerty")
    print(f"Аутентификация: {ok}")

    # --- блокировка после 3 неверных попыток (для второго клиента) ---
    bob = bank.add_client(Client(
        full_name="Борис Николаев",
        birth_date=date(1988, 3, 15),
        password="secret",
    ))
    print(f"\nСоздан клиент {bob.full_name}, проверяем блокировку после 3 неверных попыток:")
    for i in range(3):
        try:
            bank.authenticate_client(bob.client_id, "неверный")
        except Exception as e:
            print(f"Попытка {i + 1}: {e}")

    # --- заморозка/разморозка счёта ---
    bank.freeze_account(acc1.get_account_info()["account_id"])
    print(f"\nСчёт {acc1} заморожен: {acc1.get_account_info()['status']}")
    bank.unfreeze_account(acc1.get_account_info()["account_id"])
    print(f"Счёт разморожен: {acc1.get_account_info()['status']}")

    # --- поиск счетов ---
    found = bank.search_accounts(owner_name="Алина")
    print(f"\nНайдено счетов Алины: {len(found)}")

    # --- статистика ---
    print(f"\nОбщий баланс банка по валютам: {bank.get_total_balance()}")

    ranking = bank.get_clients_ranking(currency="RUB")
    print("Рейтинг клиентов по балансу (RUB):")
    for client, total in ranking:
        print(f"  {client.full_name}: {total:.2f}")

    # --- ночное ограничение: демонстрация через подставное время ---
    night_bank = Bank(name="NightBank", time_provider=lambda: datetime(2026, 1, 1, 2, 30))
    night_client = night_bank.add_client(Client(full_name="Ночной Клиент", birth_date=date(1990, 1, 1)))
    night_acc = night_bank.open_account(night_client.client_id, account_type="bank")
    print("\nПопытка операции в 02:30 ночи (искусственное время):")
    try:
        night_bank.deposit_to_account(night_acc.get_account_info()["account_id"], 100)
    except NightOperationRestrictedError as e:
        print(f"Ошибка: {e}")


if __name__ == "__main__":
    demo()
