import sqlite3
import tempfile
import os
import ast
import logging

logger = logging.getLogger(__name__)

from django.db import transaction
from .models import (
    ClipboardData,
    ClipboardFolder,
    FolderItem,
    ExtendedData,
    ClipboardFile,
)


def _ensure_bytes(val):
    """把可能的 icon_data 值规范为 bytes 或 None"""
    if val is None:
        return None
    # sqlite3 may return memoryview for BLOB
    if isinstance(val, (bytes, bytearray, memoryview)):
        return bytes(val)
    if isinstance(val, str):
        # 常见两种情形：1) 存的是 repr(bytes) -> "b'\\x01\\x02'"
        #              2) 存的是普通字符串（用 utf-8 编码）
        try:
            # 尝试把 repr 字符串解析为 bytes
            parsed = ast.literal_eval(val)
            if isinstance(parsed, (bytes, bytearray)):
                return bytes(parsed)
        except Exception:
            pass
        try:
            return val.encode("utf-8")
        except Exception:
            return None
    return None


def sync_sqlite_to_db(user, uploaded_file):
    """
    读取上传的 SQLite 文件并将数据同步到 Django Models 中。
    :param user: 当前操作的用户对象 (request.user)
    :param uploaded_file: Django 的 UploadedFile 对象 (request.FILES['file'])
    """
    tmp_file_path = None
    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        for chunk in uploaded_file.chunks():
            tmp_file.write(chunk)
        tmp_file_path = tmp_file.name

    conn = None
    try:
        conn = sqlite3.connect(tmp_file_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        with transaction.atomic():
            # 0. 获取隐私数据 ID
            private_ids = set()
            try:
                cursor.execute("SELECT item_id FROM private_data")
                for r in cursor.fetchall():
                    private_ids.add(str(r["item_id"]))
            except sqlite3.OperationalError:
                pass

            # A. Data 表
            cursor.execute("SELECT * FROM data")
            rows = cursor.fetchall()
            for row in rows:
                # 将 sqlite3.Row 转换为 dict，以便使用 .get() 方法
                row_dict = dict(row)
                client_id = str(row_dict["id"])
                if client_id in private_ids:
                    continue

                timestamp = row_dict.get("timestamp")
                try:
                    timestamp = int(timestamp) if timestamp is not None else None
                except Exception:
                    timestamp = None
                is_fav = row_dict.get("is_favorite")
                try:
                    is_fav = bool(int(is_fav)) if is_fav is not None else False
                except Exception:
                    is_fav = bool(is_fav)

                # create or update
                obj, created = ClipboardData.objects.update_or_create(
                    user=user,
                    client_id=client_id,
                    defaults={
                        "item_type": row_dict.get("item_type"),
                        "content": row_dict.get("content"),
                        "size": int(row_dict.get("size"))
                        if row_dict.get("size") not in (None, "")
                        else 0,
                        "is_favorite": is_fav,
                        "notes": row_dict.get("notes") or "",
                        "timestamp": timestamp or 0,
                    },
                )

            # B. Folders 表
            cursor.execute("SELECT * FROM folders")
            rows = cursor.fetchall()
            for row in rows:
                row_dict = dict(row)
                client_id = str(row_dict["id"])
                ClipboardFolder.objects.update_or_create(
                    user=user,
                    client_id=client_id,
                    defaults={
                        "name": row_dict.get("name") or "",
                        "num_items": int(row_dict.get("num_items"))
                        if row_dict.get("num_items") not in (None, "")
                        else 0,
                    },
                )

            # C. FolderItems 表（关联必须在 Data 和 Folders 后）
            cursor.execute("SELECT * FROM folder_items")
            rows = cursor.fetchall()
            for row in rows:
                row_dict = dict(row)
                folder_id = str(row_dict["folder_id"])
                item_id = str(row_dict["item_id"])
                if item_id in private_ids:
                    continue

                try:
                    folder = ClipboardFolder.objects.get(user=user, client_id=folder_id)
                    item = ClipboardData.objects.get(user=user, client_id=item_id)
                    # create if not exists
                    FolderItem.objects.get_or_create(folder=folder, item=item)
                except ClipboardFolder.DoesNotExist:
                    logger.debug("folder %s not found, skip folder_item", folder_id)
                except ClipboardData.DoesNotExist:
                    logger.debug("item %s not found, skip folder_item", item_id)

            # D. ExtendedData 表
            cursor.execute("SELECT * FROM extended_data")
            rows = cursor.fetchall()
            for row in rows:
                row_dict = dict(row)
                item_id = str(row_dict["item_id"])
                if item_id in private_ids:
                    continue

                ocr_text = row_dict.get("ocr_text") or ""
                raw_icon = row_dict.get("icon_data")
                icon_bytes = _ensure_bytes(raw_icon)
                try:
                    item = ClipboardData.objects.get(user=user, client_id=item_id)
                    ExtendedData.objects.update_or_create(
                        item=item,
                        defaults={
                            "ocr_text": ocr_text or "New OCR",
                            "icon_data": icon_bytes,
                        },
                    )
                except ClipboardData.DoesNotExist:
                    logger.debug(
                        "extended_data references missing item %s, skipping", item_id
                    )

    except sqlite3.Error as e:
        raise ValueError(f"SQLite 读取或同步错误: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
            except Exception:
                pass


def download_sqlite_from_db(user):
    """
    从 Django Models 中读取数据并生成一个 SQLite 文件，返回临时文件路径。
    调用者负责在使用完后删除该临时文件。
    """
    tmp_file_path = None
    with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite") as tmp_file:
        tmp_file_path = tmp_file.name

    conn = None
    try:
        conn = sqlite3.connect(tmp_file_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = OFF;")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS data (
                id TEXT PRIMARY KEY NOT NULL,
                item_type TEXT NOT NULL,
                content TEXT NOT NULL,
                size INTEGER NOT NULL,
                is_favorite INTEGER NOT NULL,
                notes TEXT,
                timestamp INTEGER NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS folders (
                id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL,
                num_items INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS folder_items (
                folder_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                PRIMARY KEY (folder_id, item_id),
                FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE,
                FOREIGN KEY (item_id) REFERENCES data(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS extended_data (
                item_id TEXT PRIMARY KEY NOT NULL,
                ocr_text TEXT,
                icon_data TEXT,
                FOREIGN KEY (item_id) REFERENCES data(id) ON DELETE CASCADE
            )
            """
        )

        # A. Data
        data_items = ClipboardData.objects.filter(user=user)
        for item in data_items:
            cursor.execute(
                """
                INSERT OR REPLACE INTO data (id, item_type, content, size, is_favorite, notes, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.client_id),
                    item.item_type,
                    item.content,
                    int(item.size) if item.size is not None else 0,
                    int(bool(item.is_favorite)),
                    item.notes or "",
                    int(item.timestamp) if item.timestamp is not None else 0,
                ),
            )

        # B. Folders
        folders = ClipboardFolder.objects.filter(user=user)
        for folder in folders:
            cursor.execute(
                "INSERT OR REPLACE INTO folders (id, name, num_items) VALUES (?, ?, ?)",
                (
                    str(folder.client_id),
                    folder.name or "",
                    int(folder.num_items) if folder.num_items is not None else 0,
                ),
            )

        # C. FolderItems
        folder_items = FolderItem.objects.filter(folder__user=user)
        for fi in folder_items:
            cursor.execute(
                "INSERT OR REPLACE INTO folder_items (folder_id, item_id) VALUES (?, ?)",
                (str(fi.folder.client_id), str(fi.item.client_id)),
            )

        # D. ExtendedData
        extended_data_items = ExtendedData.objects.filter(item__user=user)
        for ed in extended_data_items:
            icon_bytes = _ensure_bytes(ed.icon_data)
            cursor.execute(
                "INSERT OR REPLACE INTO extended_data (item_id, ocr_text, icon_data) VALUES (?, ?, ?)",
                (
                    str(ed.item.client_id),
                    ed.ocr_text or "",
                    sqlite3.Binary(icon_bytes) if icon_bytes is not None else None,
                ),
            )

        conn.commit()
        return tmp_file_path

    except sqlite3.Error as e:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
            except Exception:
                pass
        raise ValueError(f"SQLite error: {e}")

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_data_from_db(user):
    """
    从 Django Models 中读取全部用户相关数据并返回一个包含这些数据的json对象。
    """
    user_data = {
        "data": [],
        "folders": [],
        "folder_items": [],
        "extended_data": [],
    }

    # A. Data
    data_items = ClipboardData.objects.filter(user=user)
    for item in data_items:
        user_data["data"].append(
            {
                "id": str(item.client_id),
                "item_type": item.item_type,
                "content": item.content,
                "size": int(item.size) if item.size is not None else 0,
                "is_favorite": bool(item.is_favorite),
                "notes": item.notes or "",
                "timestamp": int(item.timestamp) if item.timestamp is not None else 0,
            }
        )

    # B. Folders
    folders = ClipboardFolder.objects.filter(user=user)
    for folder in folders:
        user_data["folders"].append(
            {
                "id": str(folder.client_id),
                "name": folder.name or "",
                "num_items": int(folder.num_items)
                if folder.num_items is not None
                else 0,
            }
        )

    # C. FolderItems
    folder_items = FolderItem.objects.filter(folder__user=user)
    for fi in folder_items:
        user_data["folder_items"].append(
            {
                "folder_id": str(fi.folder.client_id),
                "item_id": str(fi.item.client_id),
            }
        )

    # D. ExtendedData
    extended_data_items = ExtendedData.objects.filter(item__user=user)
    for ed in extended_data_items:
        icon_bytes = _ensure_bytes(ed.icon_data)
        user_data["extended_data"].append(
            {
                "item_id": str(ed.item.client_id),
                "ocr_text": ed.ocr_text or "",
                "icon_data": icon_bytes,
            }
        )
    return user_data


def clear_user_clipboard_data(user):
    """删除指定用户关联的所有剪贴板数据（不删除用户本身）。

    覆盖范围：
    - sync.ClipboardData / sync.ClipboardFolder / sync.FolderItem / sync.ExtendedData
    - sync.ClipboardFile（同时清理磁盘上的物理文件）

    返回：删除前的统计信息（便于 API 返回与审计日志）。
    """

    # 先“检索对应数据”做统计（满足需求 & 便于日志审计）
    counts = {
        "clipboard_files": ClipboardFile.objects.filter(user=user).count(),
        "data": ClipboardData.objects.filter(user=user).count(),
        "folders": ClipboardFolder.objects.filter(user=user).count(),
        "folder_items": FolderItem.objects.filter(folder__user=user).count(),
        "extended_data": ExtendedData.objects.filter(item__user=user).count(),
    }

    with transaction.atomic():
        # 先删依赖表，避免外键约束问题（同时也更直观）
        ExtendedData.objects.filter(item__user=user).delete()
        FolderItem.objects.filter(folder__user=user).delete()

        # 再删主表
        ClipboardFolder.objects.filter(user=user).delete()
        ClipboardData.objects.filter(user=user).delete()

        # ClipboardFile 需要调用模型 delete() 才会清理物理文件
        for f in ClipboardFile.objects.filter(user=user):
            try:
                f.delete()
            except Exception:
                # 清理失败不影响其他数据删除
                pass

    return counts
