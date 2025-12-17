from django.urls import path
from . import views

urlpatterns = [
    path("chat/", views.ChatWithClipboardView.as_view(), name="ai_chat"),
]
