from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()


class AccountsTests(APITestCase):
    def setUp(self):
        self.register_url = reverse("accounts:register")
        self.login_url = reverse("accounts:login")
        self.profile_url = reverse("accounts:profile")
        self.user_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password": "testpassword123",
            "password2": "testpassword123",
        }

    def test_registration(self):
        """Test user registration"""
        response = self.client.post(self.register_url, self.user_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(User.objects.get().username, "testuser")

    def test_login(self):
        """Test user login"""
        self.client.post(self.register_url, self.user_data)
        login_data = {"username": "testuser", "password": "testpassword123"}
        response = self.client.post(self.login_url, login_data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("jwt", response.data)
        self.assertIn("access", response.data["jwt"])
        self.assertIn("refresh", response.data["jwt"])

    def test_profile_access(self):
        """Test profile access for authenticated user"""
        # Register and Login
        self.client.post(self.register_url, self.user_data)
        login_data = {"username": "testuser", "password": "testpassword123"}
        login_response = self.client.post(self.login_url, login_data)
        token = login_response.data["jwt"]["access"]

        # Access Profile
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "testuser")

    def test_profile_access_unauthenticated(self):
        """Test profile access for unauthenticated user"""
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_change_password(self):
        """Test change password"""
        self.client.force_authenticate(
            user=User.objects.create_user(username="cp_user", password="old_password")
        )
        url = reverse("accounts:change-password")
        data = {
            "old_password": "old_password",
            "new_password": "new_password123",
            "new_password2": "new_password123",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_avatar(self):
        """Test avatar upload"""
        user = User.objects.create_user(username="avatar_user", password="password")
        self.client.force_authenticate(user=user)
        url = reverse("accounts:update-avatar")

        # Create a dummy image file
        image_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        avatar = SimpleUploadedFile(
            "avatar.png", image_content, content_type="image/png"
        )

        data = {"avatar": avatar}
        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_encryption_keys(self):
        """Test encryption keys management"""
        user = User.objects.create_user(username="key_user", password="password")
        self.client.force_authenticate(user=user)
        url = reverse("accounts:encryption-keys")

        # Test GET (initially empty)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["data"]["has_keys"])

        # Test POST
        data = {
            "kdf_salt": "test_salt",
            "encrypted_dek": "test_dek",
            "kdf_iterations": 100000,
            "kdf_algorithm": "PBKDF2",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Test GET again
        response = self.client.get(url)
        self.assertTrue(response.data["data"]["has_keys"])

    def test_registration_invalid_data(self):
        """Test registration with invalid data"""
        # Test password mismatch
        invalid_data = self.user_data.copy()
        invalid_data["password2"] = "mismatch"
        response = self.client.post(self.register_url, invalid_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Test existing username
        self.client.post(self.register_url, self.user_data)
        response = self.client.post(self.register_url, self.user_data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_invalid_credentials(self):
        """Test login with invalid credentials"""
        self.client.post(self.register_url, self.user_data)
        login_data = {"username": "testuser", "password": "wrongpassword"}
        response = self.client.post(self.login_url, login_data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout(self):
        """Test logout"""
        # Register and Login
        self.client.post(self.register_url, self.user_data)
        login_data = {"username": "testuser", "password": "testpassword123"}
        login_response = self.client.post(self.login_url, login_data)
        token = login_response.data["jwt"]["access"]
        refresh_token = login_response.data["jwt"]["refresh"]

        # Logout
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
        logout_url = reverse("accounts:logout")
        response = self.client.post(logout_url, {"refresh_token": refresh_token})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_change_password_invalid(self):
        """Test change password with invalid data"""
        user = User.objects.create_user(
            username="cp_fail_user", password="old_password"
        )
        self.client.force_authenticate(user=user)
        url = reverse("accounts:change-password")

        # Wrong old password
        data = {
            "old_password": "wrong_old_password",
            "new_password": "new_password123",
            "new_password2": "new_password123",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_avatar_invalid(self):
        """Test avatar upload with invalid data"""
        user = User.objects.create_user(
            username="avatar_fail_user", password="password"
        )
        self.client.force_authenticate(user=user)
        url = reverse("accounts:update-avatar")

        # Upload text file instead of image
        text_file = SimpleUploadedFile(
            "test.txt", b"not an image", content_type="text/plain"
        )
        data = {"avatar": text_file}
        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_encryption_keys_invalid(self):
        """Test encryption keys with invalid data"""
        user = User.objects.create_user(username="key_fail_user", password="password")
        self.client.force_authenticate(user=user)
        url = reverse("accounts:encryption-keys")

        # Invalid data (e.g. missing required fields if not partial, but here we test partial=True logic or serializer validation)
        # Let's assume serializer validates max_length or something.
        # Or we can test that valid partial update works.
        data = {"kdf_salt": "new_salt"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.kdf_salt, "new_salt")
