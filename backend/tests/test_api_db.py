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
    """测试 SQLite Push/Pull API"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@test.com",
            password="testpassword",
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

        # 创建表结构
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

        # 插入测试数据
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
        """测试上传 SQLite 文件并同步数据"""
        tmp_file_path = self._create_dummy_sqlite()
        try:
            with open(tmp_file_path, "rb") as f:
                uploaded_file = SimpleUploadedFile("test_push.sqlite", f.read())

            response = self.client.post(
                self.push_url, {"file": uploaded_file}, format="multipart"
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["code"], "SYNC_SUCCESS")

            # 验证数据已同步
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

            folder = ClipboardFolder.objects.get(
                client_id="api-folder-1", user=self.user
            )
            self.assertTrue(
                FolderItem.objects.filter(folder=folder, item=item).exists()
            )

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
        """测试下载 SQLite 文件"""
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

        # 验证下载的 SQLite 文件有效性
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


class SqliteGetAPITests(APITestCase):
    """测试 SQLite Get API - 获取用户数据的 JSON 格式"""

    def setUp(self):
        """初始化测试环境"""
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@test.com",
            password="testpassword",
        )
        self.client.force_authenticate(user=self.user)
        self.get_url = reverse("sync:get-sqlite")

    def test_get_sqlite_success_with_data(self):
        """测试成功获取包含完整数据的情况"""
        ts = int(
            datetime.datetime(
                2023, 11, 1, 12, 0, 0, tzinfo=datetime.timezone.utc
            ).timestamp()
        )

        item1 = ClipboardData.objects.create(
            user=self.user,
            client_id="test-item-1",
            item_type="text/plain",
            content="Test Content 1",
            size=14,
            is_favorite=True,
            notes="Test Note 1",
            timestamp=ts,
        )

        item2 = ClipboardData.objects.create(
            user=self.user,
            client_id="test-item-2",
            item_type="image/png",
            content="Test Content 2",
            size=100,
            is_favorite=False,
            notes="Test Note 2",
            timestamp=ts + 100,
        )

        folder = ClipboardFolder.objects.create(
            user=self.user,
            client_id="test-folder-1",
            name="Test Folder",
            num_items=2,
        )

        FolderItem.objects.create(folder=folder, item=item1)
        FolderItem.objects.create(folder=folder, item=item2)

        ExtendedData.objects.create(
            item=item1, ocr_text="OCR Text 1", icon_data=b"\x01\x02\x03"
        )
        ExtendedData.objects.create(item=item2, ocr_text="OCR Text 2", icon_data=None)

        response = self.client.get(self.get_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "database data retrieval successful")
        self.assertIn("data", response.data["data"])

        data_list = response.data["data"]["data"]
        self.assertEqual(len(data_list), 2)

        item1_data = next((d for d in data_list if d["id"] == "test-item-1"), None)
        self.assertIsNotNone(item1_data)
        self.assertEqual(item1_data["item_type"], "text/plain")
        self.assertEqual(item1_data["content"], "Test Content 1")
        self.assertEqual(item1_data["size"], 14)
        self.assertTrue(item1_data["is_favorite"])
        self.assertEqual(item1_data["notes"], "Test Note 1")
        self.assertEqual(item1_data["timestamp"], ts)

        folders_list = response.data["data"]["folders"]
        self.assertEqual(len(folders_list), 1)
        self.assertEqual(folders_list[0]["id"], "test-folder-1")

        folder_items_list = response.data["data"]["folder_items"]
        self.assertEqual(len(folder_items_list), 2)

        extended_list = response.data["data"]["extended_data"]
        self.assertEqual(len(extended_list), 2)

    def test_get_sqlite_empty_data(self):
        """测试获取空数据的情况"""
        response = self.client.get(self.get_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "database data retrieval successful")

        data = response.data["data"]
        self.assertEqual(len(data["data"]), 0)
        self.assertEqual(len(data["folders"]), 0)
        self.assertEqual(len(data["folder_items"]), 0)
        self.assertEqual(len(data["extended_data"]), 0)

    def test_get_sqlite_only_data_no_folders(self):
        """测试只有 data 没有 folders 的情况"""
        ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

        ClipboardData.objects.create(
            user=self.user,
            client_id="solo-item",
            item_type="text/plain",
            content="Solo Content",
            size=12,
            timestamp=ts,
        )

        response = self.client.get(self.get_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(len(data["folders"]), 0)
        self.assertEqual(len(data["folder_items"]), 0)

    def test_get_sqlite_unauthorized(self):
        """测试未认证用户访问"""
        self.client.force_authenticate(user=None)
        response = self.client.get(self.get_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_sqlite_data_isolation(self):
        """测试数据隔离 - 用户只能获取自己的数据"""
        other_user = User.objects.create_user(
            username="otheruser",
            email="otheruser@test.com",
            password="otherpassword",
        )
        ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

        ClipboardData.objects.create(
            user=other_user,
            client_id="other-item",
            item_type="text/plain",
            content="Other Content",
            size=13,
            timestamp=ts,
        )

        ClipboardData.objects.create(
            user=self.user,
            client_id="my-item",
            item_type="text/plain",
            content="My Content",
            size=10,
            timestamp=ts,
        )

        response = self.client.get(self.get_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_list = response.data["data"]["data"]

        self.assertEqual(len(data_list), 1)
        self.assertEqual(data_list[0]["id"], "my-item")
        self.assertEqual(data_list[0]["content"], "My Content")

    def test_get_sqlite_with_null_fields(self):
        """测试包含 NULL 字段的数据（仅 notes 允许 NULL）"""
        ts = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

        # ✅ timestamp 和 size 都必须有值
        item = ClipboardData.objects.create(
            user=self.user,
            client_id="null-item",
            item_type="text/plain",
            content="Content",
            size=7,
            is_favorite=False,
            notes=None,  # ✅ 仅 notes 可以为 NULL
            timestamp=ts,  # ✅ timestamp 必须有值
        )

        response = self.client.get(self.get_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_list = response.data["data"]["data"]
        self.assertEqual(len(data_list), 1)

        item_data = data_list[0]
        self.assertEqual(item_data["size"], 7)
        self.assertEqual(item_data["notes"], "")  # NULL 转换为空字符串
        self.assertEqual(item_data["timestamp"], ts)

    def test_get_sqlite_response_format(self):
        """测试响应格式的完整性"""
        response = self.client.get(self.get_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIn("message", response.data)
        self.assertIn("data", response.data)

        data = response.data["data"]
        self.assertIn("data", data)
        self.assertIn("folders", data)
        self.assertIn("folder_items", data)
        self.assertIn("extended_data", data)

        self.assertIsInstance(data["data"], list)
        self.assertIsInstance(data["folders"], list)
        self.assertIsInstance(data["folder_items"], list)
        self.assertIsInstance(data["extended_data"], list)
