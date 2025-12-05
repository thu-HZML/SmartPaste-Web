import sqlite3
import os
import tempfile
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import ClipboardData, ClipboardFolder, FolderItem, ExtendedData
from .db import sync_sqlite_to_db, download_sqlite_from_db

User = get_user_model()


class SyncDBTests(TestCase):
    def setUp(self):
        """在每个测试开始前，创建测试用户和一些初始数据。"""
        self.user = User.objects.create_user(
            username="testuser", password="testpassword"
        )
        self.client_data1 = ClipboardData.objects.create(
            user=self.user,
            client_id="item-1",
            item_type="text/plain",
            content="Hello",
            size=5,
            is_favorite=True,
            notes="A note",
            timestamp="2023-10-27T10:00:00Z",
        )
        self.client_data2 = ClipboardData.objects.create(
            user=self.user,
            client_id="item-2",
            item_type="image/png",
            content="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
            size=100,
        )
        self.folder1 = ClipboardFolder.objects.create(
            user=self.user, client_id="folder-1", name="My Folder", num_items=1
        )
        FolderItem.objects.create(folder=self.folder1, item=self.client_data1)
        ExtendedData.objects.create(
            item=self.client_data1, ocr_text="OCR Text", icon_data=b"\x01\x02\x03"
        )

    def test_download_sqlite_from_db(self):
        """测试从 Django Models 下载数据到 SQLite 文件。"""
        tmp_file_path = None
        try:
            tmp_file_path = download_sqlite_from_db(self.user)
            self.assertTrue(os.path.exists(tmp_file_path))

            # 连接到生成的 SQLite 文件并验证内容
            conn = sqlite3.connect(tmp_file_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 验证 data 表
            cursor.execute("SELECT * FROM data")
            rows = cursor.fetchall()
            self.assertEqual(len(rows), 2)
            row1 = next(r for r in rows if r["id"] == "item-1")
            self.assertEqual(row1["content"], "Hello")
            self.assertEqual(row1["is_favorite"], 1)

            # 验证 folders 表
            cursor.execute("SELECT * FROM folders WHERE id = ?", ("folder-1",))
            folder_row = cursor.fetchone()
            self.assertIsNotNone(folder_row)
            self.assertEqual(folder_row["name"], "My Folder")

            # 验证 folder_items 表
            cursor.execute(
                "SELECT * FROM folder_items WHERE folder_id = ? AND item_id = ?",
                ("folder-1", "item-1"),
            )
            self.assertIsNotNone(cursor.fetchone())

            # 验证 extended_data 表
            cursor.execute("SELECT * FROM extended_data WHERE item_id = ?", ("item-1",))
            ext_row = cursor.fetchone()
            self.assertIsNotNone(ext_row)
            self.assertEqual(ext_row["ocr_text"], "OCR Text")
            self.assertEqual(ext_row["icon_data"], b"\x01\x02\x03")

            conn.close()

        finally:
            # 清理临时文件
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    def _create_dummy_sqlite(self):
        """创建一个包含测试数据的临时 SQLite 文件，并返回其路径。"""
        tmp_file_path = None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite") as tmp_file:
            tmp_file_path = tmp_file.name

        conn = sqlite3.connect(tmp_file_path)
        cursor = conn.cursor()

        # 创建表
        cursor.execute(
            "CREATE TABLE data (id TEXT PRIMARY KEY, item_type TEXT, content TEXT, size INTEGER, is_favorite INTEGER, notes TEXT, timestamp TEXT)"
        )
        cursor.execute(
            "CREATE TABLE folders (id TEXT PRIMARY KEY, name TEXT, num_items INTEGER)"
        )
        cursor.execute(
            "CREATE TABLE folder_items (folder_id TEXT, item_id TEXT, PRIMARY KEY (folder_id, item_id))"
        )
        cursor.execute(
            "CREATE TABLE extended_data (item_id TEXT PRIMARY KEY, ocr_text TEXT, icon_data BLOB)"
        )

        # 插入数据
        cursor.execute(
            "INSERT INTO data VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "new-item-1",
                "text/plain",
                "New Content",
                11,
                1,
                "New Note",
                "2023-11-01T12:00:00Z",
            ),
        )
        cursor.execute(
            "INSERT INTO folders VALUES (?, ?, ?)", ("new-folder-1", "New Folder", 1)
        )
        cursor.execute(
            "INSERT INTO folder_items VALUES (?, ?)", ("new-folder-1", "new-item-1")
        )
        cursor.execute(
            "INSERT INTO extended_data VALUES (?, ?, ?)",
            ("new-item-1", "New OCR", b"\x04\x05\x06"),
        )

        conn.commit()
        conn.close()
        return tmp_file_path

    def test_sync_sqlite_to_db(self):
        """测试从 SQLite 文件同步数据到 Django Models。"""
        tmp_file_path = self._create_dummy_sqlite()
        try:
            with open(tmp_file_path, "rb") as f:
                uploaded_file = SimpleUploadedFile("test.sqlite", f.read())

            # 在同步前，新数据不应存在
            self.assertFalse(
                ClipboardData.objects.filter(client_id="new-item-1").exists()
            )

            # 执行同步
            sync_sqlite_to_db(self.user, uploaded_file)

            # 验证新数据是否已同步
            self.assertTrue(
                ClipboardData.objects.filter(client_id="new-item-1").exists()
            )
            new_item = ClipboardData.objects.get(client_id="new-item-1")
            self.assertEqual(new_item.content, "New Content")
            self.assertEqual(new_item.user, self.user)

            new_folder = ClipboardFolder.objects.get(client_id="new-folder-1")
            self.assertEqual(new_folder.name, "New Folder")

            self.assertTrue(
                FolderItem.objects.filter(folder=new_folder, item=new_item).exists()
            )

            ext_data = ExtendedData.objects.get(item=new_item)
            self.assertEqual(ext_data.ocr_text, "New OCR")

        finally:
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    def test_full_cycle(self):
        """测试下载-清空-上传-验证的完整流程。"""
        tmp_file_path = None
        try:
            # 1. 从数据库下载数据到 SQLite 文件
            tmp_file_path = download_sqlite_from_db(self.user)
            self.assertTrue(os.path.exists(tmp_file_path))

            # 2. 清空数据库中的相关数据
            ClipboardData.objects.filter(user=self.user).delete()
            ClipboardFolder.objects.filter(user=self.user).delete()
            self.assertEqual(ClipboardData.objects.filter(user=self.user).count(), 0)
            self.assertEqual(ClipboardFolder.objects.filter(user=self.user).count(), 0)

            # 3. 使用之前下载的文件同步回数据库
            with open(tmp_file_path, "rb") as f:
                uploaded_file = SimpleUploadedFile("restored.sqlite", f.read())
            sync_sqlite_to_db(self.user, uploaded_file)

            # 4. 验证数据是否已恢复
            self.assertEqual(ClipboardData.objects.filter(user=self.user).count(), 2)
            self.assertEqual(ClipboardFolder.objects.filter(user=self.user).count(), 1)

            restored_item = ClipboardData.objects.get(client_id="item-1")
            self.assertEqual(restored_item.content, self.client_data1.content)
            self.assertTrue(restored_item.is_favorite)

            restored_folder = ClipboardFolder.objects.get(client_id="folder-1")
            self.assertEqual(restored_folder.name, self.folder1.name)

            self.assertTrue(
                FolderItem.objects.filter(
                    folder=restored_folder, item=restored_item
                ).exists()
            )
            self.assertTrue(ExtendedData.objects.filter(item=restored_item).exists())

        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)
