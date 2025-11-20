from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate, get_user_model
from .serializers import (
    UserSerializer,
    RegisterSerializer,
    LoginSerializer,
    ChangePasswordSerializer
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """
    用户注册
    POST /api/accounts/register/
    Body: {
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass123!",
        "password2": "SecurePass123!",
        "phone": "13800138000"
    }
    """
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        # 自动创建 Token
        token, created = Token.objects.get_or_create(user=user)
        
        return Response({
            'user': UserSerializer(user).data,
            'token': token.key,
            'message': '注册成功'
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """
    用户登录
    POST /api/accounts/login/
    Body: {
        "username": "testuser",
        "password": "SecurePass123!"
    }
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        
        # 验证用户名和密码
        user = authenticate(username=username, password=password)
        
        if user is not None:
            # 获取或创建 Token
            token, created = Token.objects.get_or_create(user=user)
            
            return Response({
                'user': UserSerializer(user).data,
                'token': token.key,
                'message': '登录成功'
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'error': '用户名或密码错误'
            }, status=status.HTTP_401_UNAUTHORIZED)


class LogoutView(APIView):
    """
    用户登出
    POST /api/accounts/logout/
    Headers: Authorization: Token <your_token>
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # 删除用户的 Token
        try:
            request.user.auth_token.delete()
            return Response({
                'message': '登出成功'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    获取/更新用户信息
    GET /api/accounts/profile/
    PUT/PATCH /api/accounts/profile/
    Headers: Authorization: Token <your_token>
    """
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(APIView):
    """
    修改密码
    POST /api/accounts/change-password/
    Headers: Authorization: Token <your_token>
    Body: {
        "old_password": "OldPass123!",
        "new_password": "NewPass123!",
        "new_password2": "NewPass123!"
    }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        
        # 验证旧密码
        if not user.check_password(serializer.validated_data['old_password']):
            return Response({
                'error': '旧密码错误'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # 设置新密码
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        # 更新 Token
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
        
        return Response({
            'message': '密码修改成功',
            'token': token.key
        }, status=status.HTTP_200_OK)
