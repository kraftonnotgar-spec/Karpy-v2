import unittest
from pydantic import ValidationError
from .schemas import RegisterRequest


class SignupValidationTests(unittest.TestCase):
    def request(self, **values):
        return RegisterRequest(**{"name": "Real Merchant", "email": "merchant@example.com", "phone": "0684104712",
                                 "country": "TZ", "password": "Abcdef1!", "confirmPassword": "Abcdef1!", **values})

    def test_real_names_and_normalization(self):
        for name in ["A Li", "Jean-Luc O'Neill", "Jose\u0301 D\u2019Angelo", "\u674e \u738b"]:
            with self.subTest(name=name):
                self.assertTrue(self.request(name=name).name)
        self.assertEqual(self.request(name="  Real   Merchant  ").name, "Real Merchant")

    def test_numbers_markup_and_invisible_names_rejected(self):
        for name in ["11111", "John 123", "<script>", "---", "A\u200bB", "A\nB"]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                self.request(name=name)

    def test_email_format_not_guessed_provider(self):
        with self.assertRaises(ValidationError):
            self.request(email="11111")
        self.assertEqual(str(self.request(email="name@gma.co").email), "name@gma.co")
