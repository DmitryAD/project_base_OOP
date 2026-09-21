import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from client import Client, ClientStatus
from exceptions import InvalidOperationError, UnderageClientError

Client.PBKDF2_ITERATIONS = 1_000


def years_ago(years: int) -> date:
    today = date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)


class TestClientCreation(unittest.TestCase):

    def test_adult_client_is_created_active(self):
        client = Client(full_name="Анна Смирнова", birth_date=date(1990, 5, 1), password="secret")
        self.assertEqual(client.status, ClientStatus.ACTIVE)
        self.assertEqual(client.account_ids, [])
        self.assertTrue(client.client_id)

    def test_exactly_eighteen_is_allowed(self):
        client = Client(full_name="Тест", birth_date=years_ago(18), password="secret")
        self.assertEqual(client.age, 18)

    def test_underage_client_is_rejected(self):
        with self.assertRaises(UnderageClientError):
            Client(full_name="Тест", birth_date=years_ago(17), password="secret")

    def test_empty_name_is_rejected(self):
        with self.assertRaises(InvalidOperationError):
            Client(full_name="", birth_date=date(1990, 1, 1), password="secret")

    def test_birth_date_must_be_date(self):
        with self.assertRaises(InvalidOperationError):
            Client(full_name="Тест", birth_date="1990-01-01", password="secret")

    def test_password_is_required(self):
        with self.assertRaises(TypeError):
            Client(full_name="Тест", birth_date=date(1990, 1, 1))

    def test_empty_password_is_rejected(self):
        with self.assertRaises(InvalidOperationError):
            Client(full_name="Тест", birth_date=date(1990, 1, 1), password="")


class TestClientPassword(unittest.TestCase):

    def setUp(self):
        self.client = Client(full_name="Тест", birth_date=date(1990, 1, 1), password="secret")

    def test_correct_password_is_accepted(self):
        self.assertTrue(self.client.verify_password("secret"))

    def test_wrong_password_is_rejected(self):
        self.assertFalse(self.client.verify_password("wrong"))
        self.assertFalse(self.client.verify_password(None))

    def test_password_is_not_stored_in_plain_text(self):
        stored = [value for value in vars(self.client).values() if isinstance(value, (str, bytes))]
        self.assertNotIn("secret", stored)
        self.assertNotIn(b"secret", stored)

    def test_same_password_gives_different_hashes(self):
        other = Client(full_name="Другой", birth_date=date(1990, 1, 1), password="secret")
        self.assertNotEqual(self.client._password_hash, other._password_hash)

    def test_set_password_replaces_old_one(self):
        self.client.set_password("new-secret")
        self.assertTrue(self.client.verify_password("new-secret"))
        self.assertFalse(self.client.verify_password("secret"))


if __name__ == "__main__":
    unittest.main()
