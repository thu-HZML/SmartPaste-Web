import sqlite3
import tempfile
import os
from django.db import transaction
from .models import ClipboardData, ClipboardFolder, FolderItem, ExtendedData


def sync_sqlite_to_db(user, uploaded_file):
    """
    读取上传的 SQLite 文件并将数据同步到 Django Models 中。

    :param user: 当前操作的用户对象 (request.user)
    :param uploaded_file: Django 的 UploadedFile 对象 (request.FILES['file'])
    """

    # 1. 将上传的文件流保存到临时文件，因为 sqlite3.connect 需要文件路径
    tmp_file_path = None
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        for chunk in uploaded_file.chunks():
            tmp_file.write(chunk)
        tmp_file_path = tmp_file.name

    conn = None
    try:
        # 2. 连接 SQLite 数据库
        conn = sqlite3.connect(tmp_file_path)
        conn.row_factory = sqlite3.Row  # 允许通过列名访问数据 (row['id'])
        cursor = conn.cursor()

        # 3. 使用事务原子性操作，确保数据一致性
        with transaction.atomic():
            # --- A. 同步 Data 表 (ClipboardData) ---
            cursor.execute("SELECT * FROM data")
            rows = cursor.fetchall()
            for row in rows:
                # update_or_create: 如果存在则更新，不存在则创建
                ClipboardData.objects.update_or_create(
                    user=user,
                    client_id=row["id"],
                    defaults={
                        "item_type": row["item_type"],
                        "content": row["content"],
                        "size": row["size"],
                        "is_favorite": bool(
                            row["is_favorite"]
                        ),  # SQLite 0/1 -> Python False/True
                        "notes": row["notes"],
                        "timestamp": row["timestamp"],
                    },
                )

            # --- B. 同步 Folders 表 (ClipboardFolder) ---
            cursor.execute("SELECT * FROM folders")
            rows = cursor.fetchall()
            for row in rows:
                ClipboardFolder.objects.update_or_create(
                    user=user,
                    client_id=row["id"],
                    defaults={"name": row["name"], "num_items": row["num_items"]},
                )

            # --- C. 同步 FolderItems 表 (FolderItem) ---
            # 注意：必须在 Data 和 Folders 同步完成后进行
            cursor.execute("SELECT * FROM folder_items")
            rows = cursor.fetchall()
            for row in rows:
                try:
                    # 根据 client_id 和 user 查找对应的 Django 对象
                    folder = ClipboardFolder.objects.get(
                        user=user, client_id=row["folder_id"]
                    )
                    item = ClipboardData.objects.get(
                        user=user, client_id=row["item_id"]
                    )

                    # 建立多对多关联
                    FolderItem.objects.get_or_create(folder=folder, item=item)
                except (ClipboardFolder.DoesNotExist, ClipboardData.DoesNotExist):
                    # 如果引用的文件夹或数据项不存在（可能是部分同步或数据损坏），则跳过
                    continue

            # --- D. 同步 ExtendedData 表 (ExtendedData) ---
            cursor.execute("SELECT * FROM extended_data")
            rows = cursor.fetchall()
            for row in rows:
                try:
                    item = ClipboardData.objects.get(
                        user=user, client_id=row["item_id"]
                    )
                    ExtendedData.objects.update_or_create(
                        item=item,
                        defaults={
                            "ocr_text": row["ocr_text"],
                            "icon_data": row["icon_data"],
                        },
                    )
                except ClipboardData.DoesNotExist:
                    continue

    except sqlite3.Error as e:
        # 捕获 SQLite 相关错误并抛出，以便上层 API 处理
        raise ValueError(f"SQLite error: {e}")
    finally:
        if conn:
            conn.close()
        # 4. 清理临时文件
        if tmp_file_path and os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)
