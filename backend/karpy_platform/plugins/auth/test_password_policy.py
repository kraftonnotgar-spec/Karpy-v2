import unittest

from pydantic import ValidationError

from .schemas import LoginRequest, RegisterRequest, ResetPasswordRequest


class PasswordPolicyTests(unittest.TestCase):
    def test_new_passwords_require_length_and_each_character_class(self):
        for password in ["12345678", "Short1!", "123456789012", "lowercase123!", "UPPERCASE123!",
                         "NoDigitsHere!", "NoSymbols1234", "NoSymbol123  ", "A1!" + "a" * 118]:
            for schema, values in [(RegisterRequest, {"name": "Real Merchant", "phone": "+255684104712"}),
                                   (ResetPasswordRequest, {"code": "123456"})]:
                with self.subTest(schema=schema.__name__, password=password), self.assertRaises(ValidationError):
                    schema(email="merchant@example.com", password=password, confirmPassword=password, **values)

    def test_strong_passwords_are_preserved_without_trimming(self):
        for password in ["Abcdef1!", "Unique-passphrase9!", " Long passphrase 2! ", "A1!" + "a" * 117]:
            result = ResetPasswordRequest(email="merchant@example.com", code="123456", password=password, confirmPassword=password)
            self.assertEqual(result.password, password)
            self.assertNotIn(password, repr(result))

    def test_existing_passwords_can_still_authenticate(self):
        self.assertEqual(LoginRequest(email="merchant@example.com", password="12345678").password, "12345678")
