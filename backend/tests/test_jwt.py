from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from utils.jwt import (
    create_jwt_for_user,
    verify_jwt,
    blacklist_token,
    encrypt_password,
    get_user_by_id,
    jwt_authentication,
    generate_jwt,
    login_required,
    JWTAuthentication,
    get_client_ip,
    log_security_event,
    jwt_required,
)
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework.response import Response
from rest_framework import status
import datetime
from unittest.mock import MagicMock, patch
import jwt

User = get_user_model()


class JWTTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.factory = RequestFactory()

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
        self.assertEqual(str(access_token_obj.get("user_id")), str(self.user.id))

        # 4. Test token blacklisting
        result = blacklist_token(jwt_tokens["refresh"])
        self.assertTrue(result)

        # 5. Verify blacklisted token is invalid
        with self.assertRaises(Exception):
            RefreshToken(jwt_tokens["refresh"]).check_blacklist()

    def test_encrypt_password(self):
        """Test password encryption"""
        password = "mypassword"
        encrypted = encrypt_password(password)
        self.assertIsInstance(encrypted, str)
        self.assertNotEqual(password, encrypted)

        with self.assertRaises(ValueError):
            encrypt_password("")

    def test_get_user_by_id(self):
        """Test get user by ID"""
        # Existing user
        user, success = get_user_by_id(self.user.id)
        self.assertTrue(success)
        self.assertEqual(user, self.user)

        # Non-existing user
        user, success = get_user_by_id(99999)
        self.assertFalse(success)
        self.assertIsNone(user)

    def test_verify_jwt_edge_cases(self):
        """Test verify_jwt with various inputs"""
        # None
        self.assertIsNone(verify_jwt(None))

        # Invalid token
        self.assertIsNone(verify_jwt("invalid.token.string"))

        # Expired token
        expired_payload = {"user_id": self.user.id}
        # Generate a token that expired 1 hour ago
        expiry = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        token = generate_jwt(expired_payload, expiry=expiry)
        self.assertIsNone(verify_jwt(token))

        # Bearer prefix
        valid_token = generate_jwt({"user_id": self.user.id})
        payload = verify_jwt(f"Bearer {valid_token}")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["user_id"], self.user.id)

    def test_jwt_authentication_middleware(self):
        """Test JWT authentication helper"""
        # 1. No header
        request = self.factory.get("/")
        jwt_authentication(request)
        self.assertIsNone(request.user)

        # 2. Token header (skipped)
        request = self.factory.get("/", HTTP_AUTHORIZATION="Token some_token")
        jwt_authentication(request)
        self.assertIsNone(request.user)

        # 3. Valid Bearer header
        token = generate_jwt({"user_id": self.user.id})
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
        jwt_authentication(request)
        self.assertEqual(request.user, self.user)

        # 4. Invalid token
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer invalid")
        jwt_authentication(request)
        self.assertIsNone(request.user)

    def test_login_required_decorator(self):
        """Test login_required decorator"""

        @login_required
        def protected_view(request):
            return Response({"message": "success"})

        # 1. Unauthenticated
        request = self.factory.get("/")
        response = protected_view(request)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # 2. Authenticated
        token = generate_jwt({"user_id": self.user.id})
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
        response = protected_view(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 3. Class-based view method (mocking self)
        class MockView:
            @login_required
            def get(self, request):
                return Response({"message": "success"})

        view = MockView()
        response = view.get(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 4. jwt_required alias
        @jwt_required
        def protected_view_alias(request):
            return Response({"message": "success"})

        response = protected_view_alias(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_jwt_authentication_class(self):
        """Test JWTAuthentication class"""
        auth = JWTAuthentication()

        # 1. Custom JWT
        token = generate_jwt({"user_id": self.user.id})
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
        user_auth = auth.authenticate(request)
        self.assertIsNotNone(user_auth)
        self.assertEqual(user_auth[0], self.user)

        # 2. Standard JWT (SimpleJWT)
        refresh = RefreshToken.for_user(self.user)
        access = str(refresh.access_token)
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {access}")
        user_auth = auth.authenticate(request)
        self.assertIsNotNone(user_auth)
        self.assertEqual(user_auth[0], self.user)

    def test_get_client_ip(self):
        """Test get_client_ip"""
        # X-Forwarded-For
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="10.0.0.1, 10.0.0.2")
        self.assertEqual(get_client_ip(request), "10.0.0.1")

        # REMOTE_ADDR
        request = self.factory.get("/")
        # RequestFactory doesn't set REMOTE_ADDR by default in the same way, but let's check
        request.META["REMOTE_ADDR"] = "127.0.0.1"
        self.assertEqual(get_client_ip(request), "127.0.0.1")

    @patch("utils.jwt.logger")
    def test_log_security_event(self, mock_logger):
        """Test log_security_event"""
        log_security_event(
            "test_event", username="testuser", ip_address="127.0.0.1", details="details"
        )
        mock_logger.info.assert_called_with(
            "Security Event: test_event | User: testuser | IP: 127.0.0.1 | Details: details"
        )

    @patch("utils.jwt.jwt.encode")
    def test_generate_jwt_error(self, mock_encode):
        """Test generate_jwt error handling"""
        mock_encode.side_effect = Exception("Encode Error")
        from utils.jwt import JWTAuthError

        with self.assertRaises(JWTAuthError):
            generate_jwt({"user_id": 1})

    @patch("utils.jwt.jwt.decode")
    def test_verify_jwt_error(self, mock_decode):
        """Test verify_jwt error handling"""
        mock_decode.side_effect = Exception("Decode Error")
        self.assertIsNone(verify_jwt("some.token"))

    @patch("utils.jwt.scrypt.hash")
    def test_encrypt_password_error(self, mock_hash):
        """Test encrypt_password error handling"""
        mock_hash.side_effect = Exception("Hash Error")
        with self.assertRaises(ValueError):
            encrypt_password("password")

    @patch("utils.jwt.User.objects.get")
    def test_get_user_by_id_error(self, mock_get):
        """Test get_user_by_id error handling"""
        mock_get.side_effect = Exception("DB Error")
        user, success = get_user_by_id(1)
        self.assertFalse(success)
        self.assertIsNone(user)

    @patch("utils.jwt.verify_jwt")
    def test_jwt_authentication_no_user_id(self, mock_verify):
        """Test jwt_authentication with payload missing user_id"""
        mock_verify.return_value = {"username": "test"}  # No user_id
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer token")
        jwt_authentication(request)
        self.assertIsNone(request.user)

    @patch("utils.jwt.verify_jwt")
    def test_jwt_authentication_exception(self, mock_verify):
        """Test jwt_authentication exception"""
        mock_verify.side_effect = Exception("Auth Error")
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer token")
        jwt_authentication(request)
        self.assertIsNone(request.user)

    def test_login_required_no_request(self):
        """Test login_required with no request object"""

        @login_required
        def simple_func(a, b):
            return a + b

        self.assertEqual(simple_func(1, 2), 3)

    @patch("utils.jwt.jwt_authentication")
    def test_login_required_exception(self, mock_auth):
        """Test login_required exception handling"""
        mock_auth.side_effect = Exception("Auth Error")

        @login_required
        def protected_view(request):
            return Response("ok")

        request = self.factory.get("/")
        response = protected_view(request)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @patch("utils.jwt.SmartPasteRefreshToken.for_user")
    def test_create_jwt_for_user_error(self, mock_for_user):
        """Test create_jwt_for_user error handling"""
        mock_for_user.side_effect = Exception("Token Error")
        from utils.jwt import JWTAuthError

        with self.assertRaises(JWTAuthError):
            create_jwt_for_user(self.user)

    @patch("utils.jwt.RefreshToken")
    def test_blacklist_token_error(self, mock_refresh):
        """Test blacklist_token error handling"""
        mock_refresh.side_effect = Exception("Blacklist Error")
        self.assertFalse(blacklist_token("token"))

    @patch("utils.jwt.settings")
    def test_generate_jwt_expire_hours(self, mock_settings):
        """Test generate_jwt with invalid expire hours"""
        mock_settings.JWT_EXPIRE_HOURS = -1
        mock_settings.SECRET_KEY = "secret"
        mock_settings.JWT_SECRET = "secret"
        token = generate_jwt({"user_id": 1})
        self.assertIsNotNone(token)

    def test_encrypt_password_with_string_salt(self):
        """Test encrypt_password with string salt (coverage for line 141)"""
        # We need to mock settings.SALT to be a string
        with patch("utils.jwt.settings") as mock_settings:
            mock_settings.SALT = "string_salt"
            mock_settings.SECRET_KEY = "secret"
            # We also need to mock scrypt because we can't control the salt passed to it easily
            # if we want to verify the logic before scrypt.
            # Actually, the code is:
            # salt = getattr(settings, "SALT", ...)
            # if isinstance(salt, str): salt = salt.encode("utf-8")
            # key = scrypt.hash(..., salt, ...)

            # So if we set SALT to a string, it should be encoded.
            # We can verify this by mocking scrypt.hash and checking the salt arg.
            with patch("utils.jwt.scrypt.hash") as mock_hash:
                mock_hash.return_value = b"hashed"
                encrypt_password("password")

                # Check call args
                args, _ = mock_hash.call_args
                # args[1] is salt
                self.assertEqual(args[1], b"string_salt")

    @patch("utils.jwt.logger")
    def test_jwt_authentication_logging(self, mock_logger):
        """Test logging in jwt_authentication"""
        # 1. Invalid token (should log warning)
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer invalid_token")
        jwt_authentication(request)
        # Check if logger.warning was called (lines 200-202)
        self.assertTrue(mock_logger.warning.called)

        # 2. Exception (should log error)
        with patch("utils.jwt.verify_jwt", side_effect=Exception("Boom")):
            request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer token")
            jwt_authentication(request)
            # Check if logger.error was called (lines 206-207)
            self.assertTrue(mock_logger.error.called)

    def test_login_required_args_handling(self):
        """Test login_required args handling (line 228)"""

        # Case: Class method where args[0] is self, args[1] is request
        class MyView:
            @login_required
            def get(self, request):
                return Response("ok")

        view = MyView()
        # We need a valid token
        token = generate_jwt({"user_id": self.user.id})
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"Bearer {token}")

        # This should hit "request = args[1]"
        response = view.get(request)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_jwt_authentication_class_none_returns(self):
        """Test JWTAuthentication.authenticate returns None (lines 278, 282)"""
        auth = JWTAuthentication()
        request = self.factory.get("/")

        # 1. No header -> None
        self.assertIsNone(auth.authenticate(request))

        # 2. Invalid header format -> None
        request = self.factory.get("/", HTTP_AUTHORIZATION="Basic user:pass")
        self.assertIsNone(auth.authenticate(request))

    @patch("utils.jwt.verify_jwt")
    def test_jwt_authentication_class_exceptions(self, mock_verify):
        """Test JWTAuthentication.authenticate exceptions (lines 293-301)"""
        auth = JWTAuthentication()
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer token")

        # 1. InvalidTokenError -> None (caught and logged)
        mock_verify.side_effect = jwt.InvalidTokenError()
        self.assertIsNone(auth.authenticate(request))

        # 2. ExpiredSignatureError -> None
        mock_verify.side_effect = jwt.ExpiredSignatureError()
        self.assertIsNone(auth.authenticate(request))

        # 3. Generic Exception -> None
        mock_verify.side_effect = Exception("Boom")
        self.assertIsNone(auth.authenticate(request))
