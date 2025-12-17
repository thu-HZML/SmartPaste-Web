# sync/models.py

from django.db import models
from django.contrib.auth import get_user_model
import os

User = get_user_model()


def user_config_path(instance, filename):
    return f"configs/user_{instance.user.id}/config.json"


def user_file_path(instance, filename):
    # 注意：这里我们只用 ID 和文件名生成存储路径，
    # 真实的文件夹结构逻辑由 relative_path 字段在客户端维护
    return f"files/user_{instance.user.id}/{filename}"


class UserConfig(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="config")
    file = models.FileField(upload_to=user_config_path, verbose_name="config_file")
    updated_at = models.DateTimeField(auto_now=True)


class ClipboardFile(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="clipboard_files"
    )
    file = models.FileField(upload_to=user_file_path, verbose_name="clipboard_file")
    relative_path = models.CharField(
        max_length=1024, verbose_name="relative_path", default=""
    )

    md5_hash = models.CharField(max_length=32, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def delete(self, *args, **kwargs):
        if self.file and os.path.isfile(self.file.path):
            os.remove(self.file.path)
        super().delete(*args, **kwargs)


class ClipboardData(models.Model):
    """
    对应 SQLite 中的 data 表
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="clipboard_items"
    )
    # 原 SQLite 中的 id 是 TEXT PRIMARY KEY，但在 Django 中通常建议使用自增 ID 或 UUID。
    # 为了保持同步方便，我们可以保留原始 ID 作为 client_id 字段，或者直接作为主键（如果能保证全局唯一）。
    # 这里建议保留原始 ID 作为一个字段，方便后续同步逻辑。
    client_id = models.CharField(max_length=255, db_index=True)

    item_type = models.CharField(max_length=50)
    content = models.TextField()
    size = models.IntegerField()
    is_favorite = models.BooleanField(default=False)  # SQLite 中是 INTEGER (0/1)
    notes = models.TextField(null=True, blank=True)
    timestamp = models.BigIntegerField()  # 对应 SQLite INTEGER

    class Meta:
        unique_together = ("user", "client_id")  # 确保同一用户的 client_id 唯一


class ClipboardFolder(models.Model):
    """
    对应 SQLite 中的 folders 表
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="clipboard_folders"
    )
    client_id = models.CharField(max_length=255, db_index=True)
    name = models.CharField(max_length=255)
    num_items = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "client_id")


class FolderItem(models.Model):
    """
    对应 SQLite 中的 folder_items 表 (多对多关系)
    """

    # 这里不需要直接的 User 外键，因为通过 folder 或 item 都能关联到 User，
    # 但为了查询方便或权限控制，也可以加上。这里通过外键关联到上面的 Django Model。
    folder = models.ForeignKey(
        ClipboardFolder, on_delete=models.CASCADE, related_name="items"
    )
    item = models.ForeignKey(
        ClipboardData, on_delete=models.CASCADE, related_name="folders"
    )

    class Meta:
        unique_together = ("folder", "item")


class ExtendedData(models.Model):
    """
    对应 SQLite 中的 extended_data 表
    """

    # 一对一关系，关联到 ClipboardData
    item = models.OneToOneField(
        ClipboardData, on_delete=models.CASCADE, related_name="extended_data"
    )
    ocr_text = models.TextField(null=True, blank=True)
    icon_data = models.TextField(null=True, blank=True)  # 假设是 Base64 或类似文本存储
