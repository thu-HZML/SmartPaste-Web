import os
import json
import sqlite3
import tempfile
from unittest.mock import patch, MagicMock, mock_open
from django.test import TestCase, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from sync.views import (
    ConfigSyncView,
    FileUploadView,
    SqlitePushView,
    SqlitePullView,
    SqliteGetView,
)
from sync.models import UserConfig, ClipboardFile, ClipboardData, ClipboardFolder
from sync.db import _ensure_bytes, sync_sqlite_to_db

User = get_user_model()


class SyncViewsCoverageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_config_sync_view_get_not_exist(self):
        """Test ConfigSyncView GET when config does not exist"""
        # Ensure no config exists
        UserConfig.objects.filter(user=self.user).delete()

        response = self.client.get("/api/sync/config/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["error"], "配置文件不存在")

    @patch("sync.views.UserConfig.objects.get")
    def test_config_sync_view_get_exception(self, mock_get):
        """Test ConfigSyncView GET when generic exception occurs"""
        mock_get.side_effect = Exception("Unexpected error")

        response = self.client.get("/api/sync/config/")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("配置文件下载失败", str(response.data))

    def test_config_sync_view_post_no_file(self):
        """Test ConfigSyncView POST with no file"""
        response = self.client.post("/api/sync/config/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "未提供文件")

    @patch("sync.views.UserConfig.objects.get_or_create")
    def test_config_sync_view_post_exception(self, mock_get_or_create):
        """Test ConfigSyncView POST when exception occurs"""
        mock_get_or_create.side_effect = Exception("Upload error")

        file = SimpleUploadedFile("config.json", b"{}", content_type="application/json")
        response = self.client.post("/api/sync/config/", {"file": file})
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("配置上传失败", str(response.data["error"]))

    def test_file_upload_view_post_no_file(self):
        """Test FileUploadView POST with no file"""
        response = self.client.post("/api/sync/files/upload/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "未提供文件")

    @patch("sync.views.ClipboardFile.objects.create")
    def test_file_upload_view_post_exception(self, mock_create):
        """Test FileUploadView POST when exception occurs"""
        mock_create.side_effect = Exception("DB Error")

        file = SimpleUploadedFile("test.txt", b"content", content_type="text/plain")
        response = self.client.post("/api/sync/files/upload/", {"file": file})
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("文件上传失败", str(response.data["error"]))

    def test_sqlite_push_view_post_no_file(self):
        """Test SqlitePushView POST with no file"""
        # SqlitePushView uses JWTAuthentication. force_authenticate should work.
        response = self.client.post("/api/sync/sqlite/push/", {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("no database file provided", str(response.data["error"]))

    @patch("sync.views.sync_sqlite_to_db")
    def test_sqlite_push_view_post_value_error(self, mock_sync):
        """Test SqlitePushView POST when ValueError occurs (e.g. bad sqlite)"""
        mock_sync.side_effect = ValueError("Corrupt DB")

        file = SimpleUploadedFile(
            "db.sqlite", b"sqlite header", content_type="application/x-sqlite3"
        )
        response = self.client.post("/api/sync/sqlite/push/", {"db_file": file})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "SYNC_DATA_ERROR")

    @patch("sync.views.sync_sqlite_to_db")
    def test_sqlite_push_view_post_exception(self, mock_sync):
        """Test SqlitePushView POST when generic exception occurs"""
        mock_sync.side_effect = Exception("System Error")

        file = SimpleUploadedFile(
            "db.sqlite", b"sqlite header", content_type="application/x-sqlite3"
        )
        response = self.client.post("/api/sync/sqlite/push/", {"db_file": file})
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("database synchronization failed", str(response.data["error"]))

    @patch("sync.views.download_sqlite_from_db")
    def test_sqlite_pull_view_get_success(self, mock_download):
        """Test SqlitePullView GET success path (streaming)"""
        # Create a dummy file
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"sqlite content")
            tmp_path = tmp.name

        mock_download.return_value = tmp_path

        response = self.client.get("/api/sync/sqlite/pull/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # StreamingHttpResponse content is an iterator, but test client consumes it
        self.assertEqual(b"".join(response.streaming_content), b"sqlite content")

        # Verify file is deleted (mock_download returns path, view deletes it after streaming)
        # Wait, the view deletes it in 'finally' block of generator.
        # Since we consumed the stream, it should be deleted.
        self.assertFalse(os.path.exists(tmp_path))

    @patch("sync.views.download_sqlite_from_db")
    def test_sqlite_pull_view_get_value_error(self, mock_download):
        """Test SqlitePullView GET when ValueError occurs"""
        mock_download.side_effect = ValueError("Export Error")

        response = self.client.get("/api/sync/sqlite/pull/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("sync.views.download_sqlite_from_db")
    def test_sqlite_pull_view_get_exception(self, mock_download):
        """Test SqlitePullView GET when generic exception occurs"""
        mock_download.side_effect = Exception("System Error")

        response = self.client.get("/api/sync/sqlite/pull/")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @patch("sync.views.get_data_from_db")
    def test_sqlite_get_view_exception(self, mock_get_data):
        """Test SqliteGetView GET when exception occurs"""
        mock_get_data.side_effect = Exception("Retrieval Error")

        response = self.client.get("/api/sync/sqlite/get/")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


class SyncDBCoverageTests(TestCase):
    def test_ensure_bytes(self):
        """Test _ensure_bytes utility function"""
        # None
        self.assertIsNone(_ensure_bytes(None))

        # Bytes
        self.assertEqual(_ensure_bytes(b"test"), b"test")
        self.assertEqual(_ensure_bytes(bytearray(b"test")), b"test")

        # String repr of bytes
        self.assertEqual(_ensure_bytes("b'\\x01\\x02'"), b"\x01\x02")

        # Normal string
        self.assertEqual(_ensure_bytes("hello"), b"hello")

        # Malformed string repr (should fall back to utf-8 encode of the string itself)
        # "b'\\x01" is not a valid python literal for bytes if it's missing the closing quote,
        # but ast.literal_eval might raise SyntaxError.
        # The code catches Exception and tries .encode('utf-8')
        self.assertEqual(_ensure_bytes("not a repr"), b"not a repr")

        # Non-string/bytes (should return None)
        self.assertIsNone(_ensure_bytes(123))

    @patch("sqlite3.connect")
    def test_sync_sqlite_to_db_operational_error(self, mock_connect):
        """Test sync_sqlite_to_db handling of OperationalError (missing private_data table)"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Simulate OperationalError when querying private_data
        mock_cursor.execute.side_effect = [
            sqlite3.OperationalError("no such table: private_data"),  # 1st call
            [],  # data table
            [],  # folders table
            [],  # folder_items table
            [],  # extended_data table
        ]

        file = SimpleUploadedFile("db.sqlite", b"content")
        # Should not raise exception, just log/pass
        sync_sqlite_to_db(User(username="u"), file)

    @patch("sqlite3.connect")
    def test_sync_sqlite_to_db_sqlite_error(self, mock_connect):
        """Test sync_sqlite_to_db handling of general sqlite3.Error"""
        mock_connect.side_effect = sqlite3.Error("Connection failed")

        file = SimpleUploadedFile("db.sqlite", b"content")
        with self.assertRaises(ValueError):
            sync_sqlite_to_db(User(username="u"), file)

    @patch("sqlite3.connect")
    def test_sync_sqlite_to_db_data_parsing(self, mock_connect):
        """Test sync_sqlite_to_db data parsing logic (timestamps, bools)"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Mock row data
        # Row 1: Valid data
        # Row 2: Invalid timestamp/bool
        mock_rows = [
            {
                "id": "1",
                "item_type": "text",
                "content": "c1",
                "size": "10",
                "is_favorite": "1",
                "timestamp": "1000",
                "notes": "n1",
            },
            {
                "id": "2",
                "item_type": "text",
                "content": "c2",
                "size": None,
                "is_favorite": "invalid",
                "timestamp": "invalid",
                "notes": None,
            },
        ]

        # Configure cursor to return these rows for 'SELECT * FROM data'
        # We need to handle multiple execute calls.
        # 1. private_data -> []
        # 2. data -> mock_rows
        # 3. folders -> []
        # 4. folder_items -> []
        # 5. extended_data -> []

        def side_effect(query):
            if "private_data" in query:
                return []
            if "FROM data" in query:
                return mock_rows
            return []

        mock_cursor.execute.side_effect = (
            None  # Reset side effect from previous test if any
        )
        # We can't easily use side_effect for execute to return different iterables for fetchall
        # So we mock fetchall based on call count or just use a side_effect on fetchall

        mock_cursor.fetchall.side_effect = [
            [],  # private_data
            mock_rows,  # data
            [],  # folders
            [],  # folder_items
            [],  # extended_data
        ]

        user = User.objects.create(username="sync_user")
        file = SimpleUploadedFile("db.sqlite", b"content")

        sync_sqlite_to_db(user, file)

        # Verify Item 1
        item1 = ClipboardData.objects.get(client_id="1")
        self.assertEqual(item1.timestamp, 1000)
        self.assertTrue(item1.is_favorite)
        self.assertEqual(item1.size, 10)

        # Verify Item 2 (fallback values)
        item2 = ClipboardData.objects.get(client_id="2")
        self.assertEqual(item2.timestamp, 0)  # Default
        self.assertTrue(item2.is_favorite)  # bool('invalid') is True
        self.assertEqual(item2.size, 0)  # Default
