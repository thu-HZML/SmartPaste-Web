from django.urls import path
from .views import ConfigSyncView, FileUploadView, FileListView, FileDeleteView

app_name = 'sync'

urlpatterns = [
    # 配置同步
    path('config/', ConfigSyncView.as_view(), name='sync-config'),
    
    # 文件操作
    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('files/', FileListView.as_view(), name='file-list'),
    path('files/<int:pk>/', FileDeleteView.as_view(), name='file-delete'),
]