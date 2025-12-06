import os
import sqlite3
import tempfile
import datetime
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework import status
from sync.models import ClipboardData, ClipboardFolder, FolderItem, ExtendedData

User = get_user_model()


class SqliteSyncAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpassword"
        )
        self.client.force_authenticate(user=self.user)
        self.push_url = reverse("sync:push-sqlite")
        self.pull_url = reverse("sync:pull-sqlite")

    def _create_dummy_sqlite(self):
        """创建一个包含测试数据的临时 SQLite 文件，并返回其路径。"""
        tmp_file_path = None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite") as tmp_file:
            tmp_file_path = tmp_file.name

        conn = sqlite3.connect(tmp_file_path)
        cursor = conn.cursor()

        # 创建表结构 (与 db.py 中 download_sqlite_from_db 的结构一致)
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

        # 插入数据
        ts_new = int(
            datetime.datetime(
                2023, 11, 1, 12, 0, 0, tzinfo=datetime.timezone.utc
            ).timestamp()
        )
        cursor.execute(
            "INSERT INTO data VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "api-item-1",
                "text/plain",
                "API Content",
                11,
                1,
                "API Note",
                ts_new,
            ),
        )
        cursor.execute(
            "INSERT INTO folders VALUES (?, ?, ?)", ("api-folder-1", "API Folder", 1)
        )
        cursor.execute(
            "INSERT INTO folder_items VALUES (?, ?)", ("api-folder-1", "api-item-1")
        )
        cursor.execute(
            "INSERT INTO extended_data VALUES (?, ?, ?)",
            ("api-item-1", "API OCR", b"\x04\x05\x06"),
        )

        conn.commit()
        conn.close()
        return tmp_file_path

    def test_push_sqlite_success(self):
        """测试上传 SQLite 文件并同步数据 (POST)"""
        tmp_file_path = self._create_dummy_sqlite()
        try:
            with open(tmp_file_path, "rb") as f:
                # 模拟文件上传
                uploaded_file = SimpleUploadedFile("test_push.sqlite", f.read())

            response = self.client.post(
                self.push_url, {"file": uploaded_file}, format="multipart"
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["code"], "SYNC_SUCCESS")

            # 验证数据库中是否存在数据
            self.assertTrue(
                ClipboardData.objects.filter(
                    client_id="api-item-1", user=self.user
                ).exists()
            )
            item = ClipboardData.objects.get(client_id="api-item-1", user=self.user)
            self.assertEqual(item.content, "API Content")

            self.assertTrue(
                ClipboardFolder.objects.filter(
                    client_id="api-folder-1", user=self.user
                ).exists()
            )

            # 验证关联
            folder = ClipboardFolder.objects.get(
                client_id="api-folder-1", user=self.user
            )
            self.assertTrue(
                FolderItem.objects.filter(folder=folder, item=item).exists()
            )

            # 验证扩展数据
            ext = ExtendedData.objects.get(item=item)
            self.assertEqual(ext.ocr_text, "API OCR")

        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    def test_push_sqlite_no_file(self):
        """测试未上传文件的情况"""
        response = self.client.post(self.push_url, {}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pull_sqlite_success(self):
        """测试下载 SQLite 文件 (GET)"""
        # 先在数据库创建一些数据
        ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        item = ClipboardData.objects.create(
            user=self.user,
            client_id="pull-item-1",
            item_type="text/plain",
            content="Pull Content",
            size=10,
            timestamp=ts,
        )

        response = self.client.get(self.pull_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/x-sqlite3")
        self.assertTrue("attachment" in response["Content-Disposition"])

        # 验证下载的内容是否为有效的 SQLite
        content = (
            b"".join(response.streaming_content)
            if response.streaming_content
            else response.content
        )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite") as tmp_file:
            tmp_file.write(content)
            tmp_file_path = tmp_file.name

        try:
            conn = sqlite3.connect(tmp_file_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM data WHERE id=?", ("pull-item-1",))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["content"], "Pull Content")

            conn.close()
        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
