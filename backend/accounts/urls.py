from django.urls import path
from django.conf import settings             
from django.conf.urls.static import static  
from .views import (
    RegisterView,
    LoginView,
    LogoutView,
    UserProfileView,
    ChangePasswordView,
    DeleteAccountView,
)
from .views import UpdateAvatarView 
app_name = 'accounts'

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('delete/', DeleteAccountView.as_view(), name='delete'),
    path('avatar/', UpdateAvatarView.as_view(), name='update-avatar'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)