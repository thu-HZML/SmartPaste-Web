from typing import Optional
from rest_framework import status, views, generics, permissions, parsers
from rest_framework.response import Response
from rest_framework.request import Request
from django.http import FileResponse
from utils.jwt import login_required, get_client_ip, log_security_event
from .models import UserConfig, ClipboardFile
from .serializers import UserConfigSerializer, ClipboardFileSerializer

# import os
from .db import sync_sqlite_to_db
from utils.jwt import JWTAuthentication


class ConfigSyncView(views.APIView):
    """
    GET: 下载用户的 config.json
    POST: 上传/更新 config.json
    支持JWT和Token双认证
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def get(self, request: Request) -> Response:
        """下载用户配置文件"""
        try:
            config = UserConfig.objects.get(user=request.user)

            # 记录配置下载事件
            log_security_event(
                "config_download",
                username=request.user.username,
                ip_address=get_client_ip(request),
            )

            # 直接返回文件流
            return FileResponse(
                config.file.open(), as_attachment=True, filename="config.json"
            )
        except UserConfig.DoesNotExist:
            return Response(
                {"error": "配置文件不存在"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            log_security_event(
                "config_download_error",
                username=request.user.username,
                ip_address=get_client_ip(request),
                details=str(e),
            )
            return Response(
                {"error": "配置文件下载失败"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request: Request) -> Response:
        """上传用户配置文件"""
        try:
            # 获取或创建配置记录
            config_obj, created = UserConfig.objects.get_or_create(user=request.user)

            file_obj = request.FILES.get("file")
            if not file_obj:
                return Response(
                    {"error": "未提供文件"}, status=status.HTTP_400_BAD_REQUEST
                )

            # 更新文件
            config_obj.file = file_obj
            config_obj.save()

            # 记录配置上传事件
            log_security_event(
                "config_upload",
                username=request.user.username,
                ip_address=get_client_ip(request),
                details=f"File size: {file_obj.size} bytes",
            )

            return Response(
                {
                    "message": "配置同步成功",
                    "url": config_obj.file.url,
                    "created": created,
                }
            )

        except Exception as e:
            log_security_event(
                "config_upload_error",
                username=request.user.username,
                ip_address=get_client_ip(request),
                details=str(e),
            )
            return Response(
                {"error": f"配置上传失败: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class FileUploadView(views.APIView):
    """
    POST: 上传剪贴板文件 (支持单个文件上传，自动覆盖旧同名文件)
    支持JWT和Token双认证
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request: Request) -> Response:
        """上传剪贴板文件"""
        try:
            file_obj = request.FILES.get("file")
            if not file_obj:
                return Response(
                    {"error": "未提供文件"}, status=status.HTTP_400_BAD_REQUEST
                )

            # 获取前端传来的相对路径，如果没有则默认为文件名
            rel_path = request.data.get("relative_path", file_obj.name)
            # 统一路径分隔符为 / (存储时标准格式)
            rel_path = rel_path.replace("\\", "/")

            # 🔥🔥🔥 关键修改：先查找并删除该用户已有的同路径文件
            existing_files = ClipboardFile.objects.filter(
                user=request.user, relative_path=rel_path
            )
            if existing_files.exists():
                # 遍历删除（调用 model 的 delete 方法会把物理文件也删掉，避免垃圾堆积）
                for f in existing_files:
                    f.delete()
                log_security_event(
                    "file_overwrite",
                    username=request.user.username,
                    ip_address=get_client_ip(request),
                    details=f"Overwriting file: {rel_path}",
                )

            # 创建新记录
            clipboard_file = ClipboardFile.objects.create(
                user=request.user, file=file_obj, relative_path=rel_path
            )

            # 记录文件上传事件
            log_security_event(
                "file_upload",
                username=request.user.username,
                ip_address=get_client_ip(request),
                details=f"File: {rel_path}, Size: {file_obj.size} bytes",
            )

            return Response(
                ClipboardFileSerializer(clipboard_file).data,
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            log_security_event(
                "file_upload_error",
                username=request.user.username,
                ip_address=get_client_ip(request),
                details=str(e),
            )
            return Response(
                {"error": f"文件上传失败: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class FileListView(generics.ListAPIView):
    """
    GET: 获取用户所有云端文件的列表
    """

    serializer_class = ClipboardFileSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        """获取当前用户的文件列表"""
        return ClipboardFile.objects.filter(user=self.request.user).order_by(
            "-created_at"
        )


class FileDeleteView(generics.DestroyAPIView):
    """
    DELETE: 删除指定文件
    支持JWT和Token双认证
    """

    serializer_class = ClipboardFileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """获取当前用户的文件查询集"""
        return ClipboardFile.objects.filter(user=self.request.user)

    def perform_destroy(self, instance) -> None:
        """执行文件删除操作"""
        # 记录文件删除事件
        log_security_event(
            "file_delete",
            username=self.request.user.username,
            ip_address=get_client_ip(self.request),
            details=f"File: {instance.relative_path}",
        )

        # 执行删除
        super().perform_destroy(instance)


class SqliteSyncView(views.APIView):
    """
    POST: 上传 SQLite 数据库文件并同步数据到服务器
    需携带 JWT Token 进行鉴权
    """

    # 显式指定使用自定义的 JWTAuthentication，确保调用 jwt.py 中的解析逻辑
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request: Request) -> Response:
        """接收 SQLite 文件并执行同步"""
        try:
            file_obj = request.FILES.get("file")
            if not file_obj:
                return Response(
                    {"error": "no database file provided"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 记录开始同步事件
            log_security_event(
                "sqlite_sync_start",
                username=request.user.username,
                ip_address=get_client_ip(request),
                details=f"File size: {file_obj.size} bytes",
            )

            # 调用同步逻辑 (db.py)
            # 注意：sync_sqlite_to_db 内部使用了事务，保证原子性
            sync_sqlite_to_db(request.user, file_obj)

            # 记录同步成功事件
            log_security_event(
                "sqlite_sync_success",
                username=request.user.username,
                ip_address=get_client_ip(request),
            )

            return Response(
                {
                    "message": "database synchronization successful",
                    "code": "SYNC_SUCCESS",
                },
                status=status.HTTP_200_OK,
            )

        except ValueError as e:
            # 捕获业务逻辑错误（如 SQLite 文件损坏）
            log_security_event(
                "sqlite_sync_failed",
                username=request.user.username,
                ip_address=get_client_ip(request),
                details=f"Value Error: {str(e)}",
            )
            return Response(
                {"error": str(e), "code": "SYNC_DATA_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            # 捕获未预期的服务器错误
            log_security_event(
                "sqlite_sync_error",
                username=request.user.username,
                ip_address=get_client_ip(request),
                details=f"Internal Error: {str(e)}",
            )
            return Response(
                {"error": f"数据同步失败: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
