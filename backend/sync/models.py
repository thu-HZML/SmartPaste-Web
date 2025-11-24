# sync/models.py

from django.db import models
from django.contrib.auth import get_user_model
import os

User = get_user_model()

def user_config_path(instance, filename):
    return f'configs/user_{instance.user.id}/config.json'

def user_file_path(instance, filename):
    # 注意：这里我们只用 ID 和文件名生成存储路径，
    # 真实的文件夹结构逻辑由 relative_path 字段在客户端维护
    return f'files/user_{instance.user.id}/{filename}'

class UserConfig(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='config')
    file = models.FileField(upload_to=user_config_path, verbose_name="配置文件")
    updated_at = models.DateTimeField(auto_now=True)

class ClipboardFile(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='clipboard_files')
    file = models.FileField(upload_to=user_file_path, verbose_name="物理文件")

    relative_path = models.CharField(max_length=1024, verbose_name="相对路径", default="") 
    
    md5_hash = models.CharField(max_length=32, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def delete(self, *args, **kwargs):
        if self.file and os.path.isfile(self.file.path):
            os.remove(self.file.path)
        super().delete(*args, **kwargs)