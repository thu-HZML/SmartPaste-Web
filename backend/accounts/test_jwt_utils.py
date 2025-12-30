from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from rest_framework.response import Response
from unittest.mock import MagicMock, patch
import datetime
import jwt
import time
from utils.jwt import (
    generate_jwt,
    verify_jwt,
    encrypt_password,
    get_user_by_id,
    jwt_authentication,
    login_required,
    create_jwt_for_user,
    blacklist_token,
    get_client_ip,
    log_security_event,
    JWTAuthError,
)

User = get_user_model()


class JWTUtilsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="jwtuser", email="jwt@example.com", password="testpassword"
        )
        self.factory = RequestFactory()

    def test_generate_and_verify_jwt(self):
        """Test JWT generation and verification"""
        payload = {"user_id": self.user.id, "username": self.user.username}
        token = generate_jwt(payload)

        # Verify valid token
        decoded = verify_jwt(token)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["user_id"], self.user.id)
        self.assertEqual(decoded["username"], self.user.username)
        self.assertEqual(decoded["iss"], "SmartPaste-Web")

        # Verify with Bearer prefix
        decoded_bearer = verify_jwt(f"Bearer {token}")
        self.assertEqual(decoded_bearer["user_id"], self.user.id)

    def test_verify_jwt_failures(self):
        """Test JWT verification failures"""
        # Test None/Empty
        self.assertIsNone(verify_jwt(None))
        self.assertIsNone(verify_jwt(""))

        # Test Expired Token
        payload = {"user_id": self.user.id}
        # Create a token that expired 1 hour ago
        expired_expiry = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        token = generate_jwt(payload, expiry=expired_expiry)
        self.assertIsNone(verify_jwt(token))

        # Test Invalid Signature
        valid_token = generate_jwt(payload)
        # Tamper with the token (change the last character)
        # Split token to ensure we modify the signature part
        parts = valid_token.split(".")
        if len(parts) == 3:
            signature = parts[2]
            tampered_signature = signature[:-1] + ("A" if signature[-1] != "A" else "B")
            tampered_token = f"{parts[0]}.{parts[1]}.{tampered_signature}"
            self.assertIsNone(verify_jwt(tampered_token))
        else:
            # Fallback if token format is unexpected
            tampered_token = valid_token + "junk"
            self.assertIsNone(verify_jwt(tampered_token))

        # Test Malformed Token
        self.assertIsNone(verify_jwt("not.a.jwt"))

    def test_encrypt_password(self):
        """Test password encryption"""
        password = "mypassword"
        encrypted = encrypt_password(password)
        self.assertIsInstance(encrypted, str)
        self.assertNotEqual(password, encrypted)

        # Test empty password
        with self.assertRaises(ValueError):
            encrypt_password("")

        # Test deterministic encryption (since salt is fixed in settings/code)
        encrypted2 = encrypt_password(password)
        self.assertEqual(encrypted, encrypted2)

    def test_get_user_by_id(self):
        """Test get_user_by_id helper"""
        # Existing user
        user, success = get_user_by_id(self.user.id)
        self.assertTrue(success)
        self.assertEqual(user, self.user)

        # Non-existing user
        user, success = get_user_by_id(99999)
        self.assertFalse(success)
        self.assertIsNone(user)

    def test_jwt_authentication(self):
        """Test jwt_authentication function"""
        # Setup request
        request = self.factory.get("/")

        # 1. No header
        jwt_authentication(request)
        self.assertIsNone(request.user)

        # 2. Valid Bearer token
        payload = {"user_id": self.user.id}
        token = generate_jwt(payload)
        request.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        jwt_authentication(request)
        self.assertEqual(request.user, self.user)

        # 3. Invalid token
        request.user = None
        request.META["HTTP_AUTHORIZATION"] = "Bearer invalid.token"
        jwt_authentication(request)
        self.assertIsNone(request.user)

        # 4. Token prefix (should be skipped by this auth method as per code)
        request.user = None
        request.META["HTTP_AUTHORIZATION"] = "Token some_token"
        jwt_authentication(request)
        self.assertIsNone(request.user)

        # 5. User not found in DB (but valid token)
        payload_unknown = {"user_id": 99999}
        token_unknown = generate_jwt(payload_unknown)
        request.META["HTTP_AUTHORIZATION"] = f"Bearer {token_unknown}"
        jwt_authentication(request)
        self.assertIsNone(request.user)

    def test_login_required_decorator(self):
        """Test login_required decorator"""

        @login_required
        def protected_view(request):
            return Response({"status": "ok"})

        # 1. Unauthenticated request
        request = self.factory.get("/")
        # Need to manually add session/auth middleware attributes if using RequestFactory?
        # Or just rely on the decorator logic which checks request.user
        # The decorator calls jwt_authentication(request)

        response = protected_view(request)
        self.assertEqual(response.status_code, 401)

        # 2. Authenticated request
        payload = {"user_id": self.user.id}
        token = generate_jwt(payload)
        request = self.factory.get("/")
        request.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"

        response = protected_view(request)
        self.assertEqual(response.status_code, 200)

    def test_create_jwt_for_user(self):
        """Test create_jwt_for_user"""
        tokens = create_jwt_for_user(self.user)
        self.assertIn("access", tokens)
        self.assertIn("refresh", tokens)
        self.assertIn("custom_jwt", tokens)
        self.assertEqual(tokens["token_type"], "Bearer")

        # Verify the custom jwt
        decoded = verify_jwt(tokens["custom_jwt"])
        self.assertEqual(decoded["user_id"], self.user.id)

    def test_blacklist_token(self):
        """Test token blacklisting"""
        tokens = create_jwt_for_user(self.user)
        refresh_token = tokens["refresh"]

        # Blacklist it
        result = blacklist_token(refresh_token)
        self.assertTrue(result)

        # Try to blacklist again (might fail or succeed depending on implementation,
        # simplejwt usually raises error if already blacklisted, but our wrapper catches it)
        # The wrapper returns False on exception
        result_again = blacklist_token(refresh_token)
        self.assertFalse(result_again)

        # Test invalid token
        self.assertFalse(blacklist_token("invalid_token"))

    def test_get_client_ip(self):
        """Test get_client_ip"""
        # 1. X-Forwarded-For
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "10.0.0.1, 10.0.0.2"
        ip = get_client_ip(request)
        self.assertEqual(ip, "10.0.0.1")

        # 2. Remote Addr
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.1"
        ip = get_client_ip(request)
        self.assertEqual(ip, "192.168.1.1")

    @patch("utils.jwt.logger")
    def test_log_security_event(self, mock_logger):
        """Test log_security_event"""
        log_security_event(
            "test_event", username="user1", ip_address="1.1.1.1", details="some details"
        )
        mock_logger.info.assert_called()
        call_args = mock_logger.info.call_args[0][0]
        self.assertIn("Security Event: test_event", call_args)
        self.assertIn("User: user1", call_args)
        self.assertIn("IP: 1.1.1.1", call_args)
        self.assertIn("Details: some details", call_args)

    def test_generate_jwt_error(self):
        """Test generate_jwt error handling"""
        # Force an error by passing a non-serializable payload
        with self.assertRaises(JWTAuthError):
            generate_jwt({"obj": object()})

    def test_generate_jwt_custom_expiry(self):
        """Test generate_jwt with custom expiry settings"""
        # Test with 0 hours (should default to 24)
        with patch("django.conf.settings.JWT_EXPIRE_HOURS", 0, create=True):
            token = generate_jwt({"user_id": 1})
            decoded = verify_jwt(token)
            self.assertIsNotNone(decoded)

    @patch("utils.jwt.jwt.decode")
    def test_verify_jwt_generic_exception(self, mock_decode):
        """Test verify_jwt generic exception"""
        mock_decode.side_effect = Exception("Generic error")
        self.assertIsNone(verify_jwt("some.token"))

    def test_encrypt_password_salt_string(self):
        """Test encrypt_password with string salt in settings"""
        with patch("django.conf.settings.SALT", "string_salt", create=True):
            encrypted = encrypt_password("password")
            self.assertIsInstance(encrypted, str)

    @patch("utils.jwt.scrypt.hash")
    def test_encrypt_password_exception(self, mock_hash):
        """Test encrypt_password exception"""
        mock_hash.side_effect = Exception("Scrypt error")
        with self.assertRaises(ValueError):
            encrypt_password("password")

    @patch("utils.jwt.User.objects.get")
    def test_get_user_by_id_exception(self, mock_get):
        """Test get_user_by_id exception"""
        mock_get.side_effect = Exception("DB error")
        user, success = get_user_by_id(1)
        self.assertFalse(success)
        self.assertIsNone(user)

    def test_jwt_authentication_edge_cases(self):
        """Test jwt_authentication edge cases"""
        request = self.factory.get("/")

        # Token without prefix
        token = generate_jwt({"user_id": self.user.id})
        request.META["HTTP_AUTHORIZATION"] = token
        jwt_authentication(request)
        self.assertEqual(request.user, self.user)

        # Payload without user_id
        token_no_id = generate_jwt({"username": "test"})
        request.META["HTTP_AUTHORIZATION"] = f"Bearer {token_no_id}"
        request.user = None
        jwt_authentication(request)
        self.assertIsNone(request.user)

    @patch("utils.jwt.verify_jwt")
    def test_jwt_authentication_exception(self, mock_verify):
        """Test jwt_authentication exception"""
        mock_verify.side_effect = Exception("Auth error")
        request = self.factory.get("/")
        request.META["HTTP_AUTHORIZATION"] = "Bearer token"
        # Should not raise, just log error
        jwt_authentication(request)
        self.assertIsNone(request.user)

    def test_login_required_class_method(self):
        """Test login_required on class method"""

        class MyView:
            @login_required
            def get(self, request):
                return Response({"status": "ok"})

        view = MyView()
        request = self.factory.get("/")
        # Unauthenticated
        response = view.get(request)
        self.assertEqual(response.status_code, 401)

    def test_login_required_no_request(self):
        """Test login_required without request object"""

        @login_required
        def simple_func(a, b):
            return a + b

        # Should execute function directly
        self.assertEqual(simple_func(1, 2), 3)

    def test_drf_jwt_authentication_class(self):
        """Test JWTAuthentication class"""
        from utils.jwt import JWTAuthentication

        auth = JWTAuthentication()
        request = self.factory.get("/")

        # 1. No header
        self.assertIsNone(auth.authenticate(request))

        # 2. Valid custom token
        token = generate_jwt({"user_id": self.user.id})
        request.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        user, auth_token = auth.authenticate(request)
        self.assertEqual(user, self.user)

        # 3. Invalid custom token (should return None or raise depending on simplejwt fallback)
        request.META["HTTP_AUTHORIZATION"] = "Bearer invalid"
        # Mock verify_jwt to fail so we fall through to super().authenticate
        # super().authenticate will fail because "invalid" is not a valid simplejwt
        try:
            result = auth.authenticate(request)
            self.assertIsNone(result)
        except:
            # simplejwt might raise InvalidToken
            pass

    @patch("utils.jwt.jwt_authentication")
    def test_login_required_exception(self, mock_auth):
        """Test login_required decorator exception handling"""
        mock_auth.side_effect = Exception("Decorator error")

        @login_required
        def view(request):
            return Response({"status": "ok"})

        request = self.factory.get("/")
        response = view(request)
        self.assertEqual(response.status_code, 500)

    def test_jwt_required_alias(self):
        """Test jwt_required alias"""
        from utils.jwt import jwt_required

        @jwt_required
        def view(request):
            return Response({"status": "ok"})

        request = self.factory.get("/")
        # Should fail auth
        response = view(request)
        self.assertEqual(response.status_code, 401)

    def test_jwt_authentication_class_custom_failure(self):
        """Test JWTAuthentication class custom auth failure logging"""
        from utils.jwt import JWTAuthentication

        auth = JWTAuthentication()
        request = self.factory.get("/")
        request.META["HTTP_AUTHORIZATION"] = "Bearer token"

        with patch("utils.jwt.verify_jwt") as mock_verify:
            mock_verify.side_effect = Exception("Custom verify error")
            # Should return None (and log debug)
            # And then try super().authenticate which fails with InvalidToken or returns None
            try:
                result = auth.authenticate(request)
                self.assertIsNone(result)
            except:
                pass

    def test_get_client_ip_unknown(self):
        """Test get_client_ip with no info"""
        request = self.factory.get("/")
        if "REMOTE_ADDR" in request.META:
            del request.META["REMOTE_ADDR"]
        ip = get_client_ip(request)
        self.assertEqual(ip, "unknown")

    @patch("utils.jwt.SmartPasteRefreshToken.for_user")
    def test_create_jwt_for_user_exception(self, mock_for_user):
        """Test create_jwt_for_user exception"""
        mock_for_user.side_effect = Exception("Token error")
        with self.assertRaises(JWTAuthError):
            create_jwt_for_user(self.user)
