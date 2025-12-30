from django.urls import path
from .views import (
    ConfigSyncView,
    FileUploadView,
    FileListView,
    FileDeleteView,
    SqlitePushView,
    SqlitePullView,
    SqliteGetView,
    SqliteClearView,
)

app_name = "sync"

urlpatterns = [
    # 配置同步
    path("config/", ConfigSyncView.as_view(), name="sync-config"),
    # SQLite 同步
    path("sqlite/push/", SqlitePushView.as_view(), name="push-sqlite"),
    path("sqlite/pull/", SqlitePullView.as_view(), name="pull-sqlite"),
    path("sqlite/get/", SqliteGetView.as_view(), name="get-sqlite"),
    path(
        "sqlite/clear/<int:user_id>/",
        SqliteClearView.as_view(),
        name="sqlite-clear",
    ),
    # 文件操作
    path("files/upload/", FileUploadView.as_view(), name="file-upload"),
    path("files/", FileListView.as_view(), name="file-list"),
    path("files/<int:pk>/", FileDeleteView.as_view(), name="file-delete"),
]
