import sqlite3
import os
import tempfile
import datetime
import ast
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import ClipboardData, ClipboardFolder, FolderItem, ExtendedData
from .db import sync_sqlite_to_db, download_sqlite_from_db, get_data_from_db


User = get_user_model()


class SyncDBTests(TestCase):
    def setUp(self):
        """在每个测试开始前，创建测试用户和一些初始数据。"""
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@test.com",  # 添加 email
            password="testpassword",
        )
        # 使用 UTC epoch seconds 作为 timestamp（符合模型的数字类型）
        ts1 = int(
            datetime.datetime(
                2023, 10, 27, 10, 0, 0, tzinfo=datetime.timezone.utc
            ).timestamp()
        )
        self.client_data1 = ClipboardData.objects.create(
            user=self.user,
            client_id="item-1",
            item_type="text/plain",
            content="Hello",
            size=5,
            is_favorite=True,
            notes="A note",
            timestamp=ts1,
        )
        self.client_data2 = ClipboardData.objects.create(
            user=self.user,
            client_id="item-2",
            item_type="image/png",
            content="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
            size=100,
            timestamp=ts1,  # <- 新增：提供必需的 timestamp 字段，使用整数 epoch seconds
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
        conn = None
        try:
            tmp_file_path = download_sqlite_from_db(self.user)
            conn = sqlite3.connect(tmp_file_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 检查 data
            cursor.execute("SELECT * FROM data")
            data_rows = cursor.fetchall()
            self.assertEqual(len(data_rows), 2)

            # 检查 folders
            cursor.execute("SELECT * FROM folders")
            folder_rows = cursor.fetchall()
            self.assertEqual(len(folder_rows), 1)

            # 检查 extended_data 并兼容字符串/bytes 情形
            cursor.execute("SELECT * FROM extended_data")
            ext_row = cursor.fetchone()
            self.assertIsNotNone(ext_row)
            icon_raw = ext_row["icon_data"]
            if isinstance(icon_raw, str):
                try:
                    icon_val = ast.literal_eval(icon_raw)
                except Exception:
                    icon_val = icon_raw.encode("utf-8")
            else:
                icon_val = icon_raw
            self.assertEqual(icon_val, b"\x01\x02\x03")
        finally:
            # 先关闭连接，Windows 下才能删除临时文件
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.remove(tmp_file_path)
                except Exception:
                    pass

    def _create_dummy_sqlite(self):
        """创建一个包含测试数据的临时 SQLite 文件，并返回其路径。"""
        tmp_file_path = None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite") as tmp_file:
            tmp_file_path = tmp_file.name

        conn = sqlite3.connect(tmp_file_path)
        cursor = conn.cursor()

        # 创建表
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
        # 新增 private_data 表
        cursor.execute(
            "CREATE TABLE private_data (item_id TEXT PRIMARY KEY NOT NULL, FOREIGN KEY (item_id) REFERENCES data(id) ON DELETE CASCADE)"
        )

        # 插入数据（timestamp 使用整数 epoch）
        ts_new = int(
            datetime.datetime(
                2023, 11, 1, 12, 0, 0, tzinfo=datetime.timezone.utc
            ).timestamp()
        )
        cursor.execute(
            "INSERT INTO data VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "new-item-1",
                "text/plain",
                "New Content",
                11,
                1,
                "New Note",
                ts_new,
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

        # 插入隐私数据
        cursor.execute(
            "INSERT INTO data VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "private-item-1",
                "text/plain",
                "Private Content",
                15,
                0,
                "Private Note",
                ts_new,
            ),
        )
        cursor.execute("INSERT INTO private_data VALUES (?)", ("private-item-1",))
        cursor.execute(
            "INSERT INTO folder_items VALUES (?, ?)", ("new-folder-1", "private-item-1")
        )
        cursor.execute(
            "INSERT INTO extended_data VALUES (?, ?, ?)",
            ("private-item-1", "Private OCR", b"\x07\x08\x09"),
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
            self.assertFalse(
                ClipboardData.objects.filter(client_id="private-item-1").exists()
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

            # 验证隐私数据未同步
            self.assertFalse(
                ClipboardData.objects.filter(client_id="private-item-1").exists()
            )

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

    def test_get_data_from_db(self):
        """测试从 Django Models 获取用户数据的 JSON 格式。"""
        user_data = get_data_from_db(self.user)

        # 验证返回的数据结构
        self.assertIn("data", user_data)
        self.assertIn("folders", user_data)
        self.assertIn("folder_items", user_data)
        self.assertIn("extended_data", user_data)
        self.assertIsInstance(user_data["data"], list)
        self.assertIsInstance(user_data["folders"], list)
        self.assertIsInstance(user_data["folder_items"], list)
        self.assertIsInstance(user_data["extended_data"], list)

        # 验证 data 数据
        self.assertEqual(len(user_data["data"]), 2)
        # 找到对应的数据项
        data_item1 = next(
            (item for item in user_data["data"] if item["id"] == "item-1"), None
        )
        self.assertIsNotNone(data_item1)
        self.assertEqual(data_item1["content"], "Hello")
        self.assertEqual(data_item1["item_type"], "text/plain")
        self.assertEqual(data_item1["size"], 5)
        self.assertTrue(data_item1["is_favorite"])
        self.assertEqual(data_item1["notes"], "A note")
        self.assertIsInstance(data_item1["timestamp"], int)

        data_item2 = next(
            (item for item in user_data["data"] if item["id"] == "item-2"), None
        )
        self.assertIsNotNone(data_item2)
        self.assertEqual(data_item2["item_type"], "image/png")
        self.assertFalse(data_item2["is_favorite"])

        # 验证 folders 数据
        self.assertEqual(len(user_data["folders"]), 1)
        folder = user_data["folders"][0]
        self.assertEqual(folder["id"], "folder-1")
        self.assertEqual(folder["name"], "My Folder")
        self.assertEqual(folder["num_items"], 1)

        # 验证 folder_items 数据
        self.assertEqual(len(user_data["folder_items"]), 1)
        folder_item = user_data["folder_items"][0]
        self.assertEqual(folder_item["folder_id"], "folder-1")
        self.assertEqual(folder_item["item_id"], "item-1")

        # 验证 extended_data 数据
        self.assertEqual(len(user_data["extended_data"]), 1)
        extended = user_data["extended_data"][0]
        self.assertEqual(extended["item_id"], "item-1")
        self.assertEqual(extended["ocr_text"], "OCR Text")
        self.assertEqual(extended["icon_data"], b"\x01\x02\x03")

    def test_get_data_from_db_empty_user(self):
        """测试获取没有数据的用户的数据。"""
        empty_user = User.objects.create_user(
            username="emptyuser",
            email="emptyuser@test.com",  # 添加唯一 email
            password="testpassword",
        )
        user_data = get_data_from_db(empty_user)

        # 验证返回空列表
        self.assertEqual(len(user_data["data"]), 0)
        self.assertEqual(len(user_data["folders"]), 0)
        self.assertEqual(len(user_data["folder_items"]), 0)
        self.assertEqual(len(user_data["extended_data"]), 0)

        # 验证数据结构完整
        self.assertIn("data", user_data)
        self.assertIn("folders", user_data)
        self.assertIn("folder_items", user_data)
        self.assertIn("extended_data", user_data)

    def test_get_data_from_db_data_types(self):
        """测试返回数据的类型正确性。"""
        user_data = get_data_from_db(self.user)

        # 验证 data 字段类型
        for item in user_data["data"]:
            self.assertIsInstance(item["id"], str)
            self.assertIsInstance(item["item_type"], str)
            self.assertIsInstance(item["content"], str)
            self.assertIsInstance(item["size"], int)
            self.assertIsInstance(item["is_favorite"], bool)
            self.assertIsInstance(item["notes"], str)
            self.assertIsInstance(item["timestamp"], int)

        # 验证 folders 字段类型
        for folder in user_data["folders"]:
            self.assertIsInstance(folder["id"], str)
            self.assertIsInstance(folder["name"], str)
            self.assertIsInstance(folder["num_items"], int)

        # 验证 folder_items 字段类型
        for fi in user_data["folder_items"]:
            self.assertIsInstance(fi["folder_id"], str)
            self.assertIsInstance(fi["item_id"], str)

        # 验证 extended_data 字段类型
        for ed in user_data["extended_data"]:
            self.assertIsInstance(ed["item_id"], str)
            self.assertIsInstance(ed["ocr_text"], str)
            self.assertTrue(isinstance(ed["icon_data"], (bytes, type(None))))

    def test_get_data_from_db_user_isolation(self):
        """测试数据用户隔离性，确保只返回指定用户的数据。"""
        # 创建另一个用户及其数据
        other_user = User.objects.create_user(
            username="otheruser",
            email="otheruser@test.com",  # 添加唯一 email
            password="testpassword",
        )
        ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        ClipboardData.objects.create(
            user=other_user,
            client_id="other-item-1",
            item_type="text/plain",
            content="Other Content",
            size=10,
            timestamp=ts,
        )
        ClipboardFolder.objects.create(
            user=other_user,
            client_id="other-folder-1",
            name="Other Folder",
            num_items=0,
        )

        # 获取第一个用户的数据
        user_data = get_data_from_db(self.user)

        # 确保不包含其他用户的数据
        data_ids = [item["id"] for item in user_data["data"]]
        self.assertNotIn("other-item-1", data_ids)

        folder_ids = [folder["id"] for folder in user_data["folders"]]
        self.assertNotIn("other-folder-1", folder_ids)

        # 确保包含正确的数据数量
        self.assertEqual(len(user_data["data"]), 2)
        self.assertEqual(len(user_data["folders"]), 1)
