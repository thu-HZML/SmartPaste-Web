from rest_framework import status, views, generics, permissions, parsers
from rest_framework.response import Response
from django.http import FileResponse
from .models import UserConfig, ClipboardFile
from .serializers import UserConfigSerializer, ClipboardFileSerializer
import os

class ConfigSyncView(views.APIView):
    """
    GET: 下载用户的 config.json
    POST: 上传/更新 config.json
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def get(self, request):
        try:
            config = UserConfig.objects.get(user=request.user)
            # 直接返回文件流
            return FileResponse(config.file.open(), as_attachment=True, filename='config.json')
        except UserConfig.DoesNotExist:
            return Response({'error': '配置文件不存在'}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        # 获取或创建配置记录
        config_obj, created = UserConfig.objects.get_or_create(user=request.user)
        
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': '未提供文件'}, status=status.HTTP_400_BAD_REQUEST)

        # 更新文件
        config_obj.file = file_obj
        config_obj.save()
        
        return Response({'message': '配置同步成功', 'url': config_obj.file.url})


class FileUploadView(views.APIView):
    """
    POST: 上传剪贴板文件 (支持单个文件上传，自动覆盖旧同名文件)
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': '未提供文件'}, status=status.HTTP_400_BAD_REQUEST)

        # 获取前端传来的相对路径，如果没有则默认为文件名
        rel_path = request.data.get('relative_path', file_obj.name)
        # 统一路径分隔符为 / (存储时标准格式)
        rel_path = rel_path.replace('\\', '/')

        # 🔥🔥🔥 关键修改：先查找并删除该用户已有的同路径文件
        existing_files = ClipboardFile.objects.filter(user=request.user, relative_path=rel_path)
        if existing_files.exists():
            # 遍历删除（调用 model 的 delete 方法会把物理文件也删掉，避免垃圾堆积）
            for f in existing_files:
                f.delete()

        # 创建新记录
        clipboard_file = ClipboardFile.objects.create(
            user=request.user,
            file=file_obj,
            relative_path=rel_path 
        )

        return Response(
            ClipboardFileSerializer(clipboard_file).data, 
            status=status.HTTP_201_CREATED
        )

class FileListView(generics.ListAPIView):
    """
    GET: 获取用户所有云端文件的列表
    """
    serializer_class = ClipboardFileSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None 
    def get_queryset(self):
        return ClipboardFile.objects.filter(user=self.request.user).order_by('-created_at')

class FileDeleteView(generics.DestroyAPIView):
    """
    DELETE: 删除指定文件
    """
    serializer_class = ClipboardFileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ClipboardFile.objects.filter(user=self.request.user)