from django.db import models
from django.contrib.auth.models import AbstractUser

def user_avatar_path(instance, filename):
    # 将文件重命名为: avatars/user_id/filename
    # 这样可以避免文件名冲突，也方便管理
    return f'avatars/user_{instance.id}/{filename}'
class User(AbstractUser):
    """
    自定义用户模型
    继承 Django 的 AbstractUser，可以根据需要添加额外字段
    """

    email = models.EmailField(unique=True, verbose_name="email")  # unique=True
    phone = models.CharField(
        max_length=11, blank=True, null=True, verbose_name="telephone"
    )
    bio = models.TextField(blank=True, null=True, verbose_name="biography")
    avatar = models.ImageField(
        upload_to=user_avatar_path, # 指定上传路径
        blank=True, 
        null=True, 
        verbose_name="avatar"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="created time")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="updated time")

    class Meta:
        db_table = "users"
        verbose_name = "user"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.username
