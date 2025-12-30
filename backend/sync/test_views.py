import sqlite3
import os
import tempfile
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.authtoken.models import Token
from utils.jwt import generate_jwt
from .models import (
    ClipboardData,
    ClipboardFolder,
    FolderItem,
    ExtendedData,
    UserConfig,
    ClipboardFile,
)

User = get_user_model()


class SyncAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="sync_api_user", password="password"
        )
        self.client.force_authenticate(user=self.user)

    def test_config_sync(self):
        """Test config sync (GET/POST)"""
        url = reverse("sync:sync-config")

        # Test GET (not found initially)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Test POST
        config_content = b'{"theme": "dark"}'
        config_file = SimpleUploadedFile(
            "config.json", config_content, content_type="application/json"
        )
        response = self.client.post(url, {"file": config_file}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Test GET (found)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.getvalue(), config_content)

    def test_file_upload_and_list_and_delete(self):
        """Test file upload, list and delete"""
        upload_url = reverse("sync:file-upload")
        list_url = reverse("sync:file-list")

        # Test Upload
        file_content = b"test file content"
        file_obj = SimpleUploadedFile(
            "test.txt", file_content, content_type="text/plain"
        )
        response = self.client.post(
            upload_url,
            {"file": file_obj, "relative_path": "test.txt"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        file_id = response.data["id"]

        # Test List
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["relative_path"], "test.txt")

        # Test Delete
        delete_url = reverse("sync:file-delete", kwargs={"pk": file_id})
        response = self.client.delete(delete_url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify Delete
        response = self.client.get(list_url)
        self.assertEqual(len(response.data), 0)

    def test_sqlite_push(self):
        """Test sqlite push"""
        url = reverse("sync:push-sqlite")

        # Create a dummy sqlite file
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
            conn = sqlite3.connect(tmp.name)
            cursor = conn.cursor()
            # Create all necessary tables
            cursor.execute(
                "CREATE TABLE data (id TEXT PRIMARY KEY NOT NULL, item_type TEXT NOT NULL, content TEXT NOT NULL, size INTEGER NOT NULL, is_favorite INTEGER NOT NULL, notes TEXT, timestamp INTEGER NOT NULL)"
            )
            cursor.execute(
                "CREATE TABLE folders (id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, num_items INTEGER NOT NULL DEFAULT 0)"
            )
            cursor.execute(
                "CREATE TABLE folder_items (folder_id TEXT NOT NULL, item_id TEXT NOT NULL, PRIMARY KEY (folder_id, item_id), FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE, FOREIGN KEY (item_id) REFERENCES data(id) ON DELETE CASCADE)"
            )
            cursor.execute(
                "CREATE TABLE extended_data (item_id TEXT PRIMARY KEY NOT NULL, ocr_text TEXT, icon_data TEXT, FOREIGN KEY (item_id) REFERENCES data(id) ON DELETE CASCADE)"
            )

            cursor.execute(
                "INSERT INTO data VALUES ('item1', 'text', 'content', 5, 0, '', 123456)"
            )
            conn.commit()
            conn.close()
            tmp.seek(0)
            content = open(tmp.name, "rb").read()

        db_file = SimpleUploadedFile(
            "db.sqlite", content, content_type="application/x-sqlite3"
        )
        response = self.client.post(url, {"db_file": db_file}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(ClipboardData.objects.filter(client_id="item1").exists())

        os.unlink(tmp.name)

    def test_sqlite_push_invalid_file(self):
        """Test sqlite push with invalid file"""
        url = reverse("sync:push-sqlite")

        # No file
        response = self.client.post(url, {}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid file content
        invalid_file = SimpleUploadedFile(
            "db.sqlite", b"not a sqlite file", content_type="application/x-sqlite3"
        )
        response = self.client.post(url, {"db_file": invalid_file}, format="multipart")
        self.assertIn(
            response.status_code,
            [status.HTTP_400_BAD_REQUEST, status.HTTP_500_INTERNAL_SERVER_ERROR],
        )

    def test_file_upload_overwrite(self):
        """Test file upload overwrite logic"""
        upload_url = reverse("sync:file-upload")

        # Upload first time
        file_obj1 = SimpleUploadedFile(
            "test.txt", b"content 1", content_type="text/plain"
        )
        response1 = self.client.post(
            upload_url,
            {"file": file_obj1, "relative_path": "test.txt"},
            format="multipart",
        )
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)

        self.assertEqual(ClipboardFile.objects.count(), 1)
        # Ensure file is closed after reading
        f1 = ClipboardFile.objects.first()
        with f1.file.open("rb") as f:
            self.assertEqual(f.read(), b"content 1")

        # Upload second time (overwrite)
        file_obj2 = SimpleUploadedFile(
            "test.txt", b"content 2", content_type="text/plain"
        )
        response2 = self.client.post(
            upload_url,
            {"file": file_obj2, "relative_path": "test.txt"},
            format="multipart",
        )
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)

        self.assertEqual(ClipboardFile.objects.count(), 1)
        f2 = ClipboardFile.objects.first()
        with f2.file.open("rb") as f:
            self.assertEqual(f.read(), b"content 2")

    def test_sqlite_clear_self(self):
        """普通用户可清空自己的 SQLite/剪贴板同步数据，不影响用户本身。"""
        # 准备剪贴板结构化数据
        item = ClipboardData.objects.create(
            user=self.user,
            client_id="clear-item-1",
            item_type="text",
            content="hello",
            size=5,
            is_favorite=False,
            notes="",
            timestamp=123,
        )
        folder = ClipboardFolder.objects.create(
            user=self.user, client_id="clear-folder-1", name="Folder", num_items=1
        )
        FolderItem.objects.create(folder=folder, item=item)
        ExtendedData.objects.create(item=item, ocr_text="OCR", icon_data="icon")

        # 准备剪贴板文件
        file_obj = SimpleUploadedFile(
            "clear.txt", b"file content", content_type="text/plain"
        )
        clipboard_file = ClipboardFile.objects.create(
            user=self.user, file=file_obj, relative_path="clear.txt"
        )
        file_path = clipboard_file.file.path
        self.assertTrue(os.path.exists(file_path))

        url = reverse("sync:sqlite-clear", kwargs={"user_id": self.user.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # 用户仍存在
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

        # 所有剪贴板相关表都清空
        self.assertEqual(ClipboardData.objects.filter(user=self.user).count(), 0)
        self.assertEqual(ClipboardFolder.objects.filter(user=self.user).count(), 0)
        self.assertEqual(FolderItem.objects.filter(folder__user=self.user).count(), 0)
        self.assertEqual(ExtendedData.objects.filter(item__user=self.user).count(), 0)
        self.assertEqual(ClipboardFile.objects.filter(user=self.user).count(), 0)

        # 物理文件应被清理（若存储后端支持本地 path）
        self.assertFalse(os.path.exists(file_path))

    def test_sqlite_clear_forbidden_other_user(self):
        """普通用户不能清空其他用户的 SQLite/剪贴板同步数据。"""
        other = User.objects.create_user(
            username="other_user", email="other_user@example.com", password="password"
        )
        url = reverse("sync:sqlite-clear", kwargs={"user_id": other.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_sqlite_clear_admin_can_clear_other_user(self):
        """管理员可清空任意用户的 SQLite/剪贴板同步数据，且不删除用户。"""
        other = User.objects.create_user(
            username="other_user2", email="other_user2@example.com", password="password"
        )
        ClipboardData.objects.create(
            user=other,
            client_id="other-item-1",
            item_type="text",
            content="hello",
            size=5,
            is_favorite=False,
            notes="",
            timestamp=123,
        )

        self.user.is_staff = True
        self.user.save()

        url = reverse("sync:sqlite-clear", kwargs={"user_id": other.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue(User.objects.filter(id=other.id).exists())
        self.assertEqual(ClipboardData.objects.filter(user=other).count(), 0)

    def test_sqlite_clear_accepts_jwt_bearer(self):
        """sqlite-clear 仅允许 JWT Bearer 通过鉴权。"""
        # 取消 force_authenticate，改用真实 Authorization header
        self.client.force_authenticate(user=None)
        jwt_token = generate_jwt(
            {
                "user_id": self.user.id,
                "username": self.user.username,
                "email": self.user.email,
            }
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_token}")

        url = reverse("sync:sqlite-clear", kwargs={"user_id": self.user.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_sqlite_clear_rejects_drf_token_auth(self):
        """sqlite-clear 禁止 DRF TokenAuthentication（JWT-only）。"""
        self.client.force_authenticate(user=None)
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        url = reverse("sync:sqlite-clear", kwargs={"user_id": self.user.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
