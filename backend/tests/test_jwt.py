from django.test import TestCase
from django.contrib.auth import get_user_model
from utils.jwt import create_jwt_for_user, verify_jwt, blacklist_token
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken

User = get_user_model()


class JWTTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_jwt_functionality(self):
        """Test JWT functionality"""
        # 1. Test JWT generation
        jwt_tokens = create_jwt_for_user(self.user)
        self.assertIn("access", jwt_tokens)
        self.assertIn("refresh", jwt_tokens)
        self.assertIn("custom_jwt", jwt_tokens)
        self.assertEqual(jwt_tokens["token_type"], "Bearer")

        # 2. Test custom JWT verification
        custom_jwt = jwt_tokens["custom_jwt"]
        payload = verify_jwt(custom_jwt)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("user_id"), self.user.id)
        self.assertEqual(payload.get("username"), self.user.username)
        self.assertEqual(payload.get("email"), self.user.email)

        # 3. Test standard JWT verification
        access_token = jwt_tokens["access"]
        access_token_obj = AccessToken(access_token)
        self.assertEqual(access_token_obj.get("user_id"), self.user.id)

        # 4. Test token blacklisting
        result = blacklist_token(jwt_tokens["refresh"])
        self.assertTrue(result)

        # 5. Verify blacklisted token is invalid
        with self.assertRaises(Exception):
            RefreshToken(jwt_tokens["refresh"]).check_blacklist()
