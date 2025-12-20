import sqlite3
import os
import tempfile
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
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
