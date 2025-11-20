from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    自定义用户模型
    继承 Django 的 AbstractUser，可以根据需要添加额外字段
    """
    email = models.EmailField(unique=True, verbose_name="邮箱")
    phone = models.CharField(max_length=11, blank=True, null=True, verbose_name="手机号")
    avatar = models.URLField(blank=True, null=True, verbose_name="头像")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "users"
        verbose_name = "用户"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.username
