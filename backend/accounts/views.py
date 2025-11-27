from typing import Dict, Any, Optional
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import AbstractUser
from utils.jwt import (
    create_jwt_for_user,
    blacklist_token,
    get_client_ip,
    log_security_event,
)
from .serializers import (
    UserSerializer,
    RegisterSerializer,
    LoginSerializer,
    ChangePasswordSerializer,
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """
    用户注册API视图

    支持新用户注册并返回JWT和Token双重认证令牌

    Endpoint: POST /api/accounts/register/
    Permission: AllowAny (公开接口)

    Request Body:
        username (str): 用户名
        email (str): 邮箱地址
        password (str): 密码
        password2 (str): 确认密码
        phone (str, optional): 手机号码

    Response:
        201: 注册成功，返回用户信息和认证令牌
        400: 请求数据验证失败
    """

    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # 创建Token（保持向后兼容）
        token, created = Token.objects.get_or_create(user=user)

        # 创建JWT令牌
        try:
            jwt_tokens = create_jwt_for_user(user)

            # 记录注册事件
            log_security_event(
                "user_register",
                username=user.username,
                ip_address=get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )

            return Response(
                {
                    "user": UserSerializer(user).data,
                    "token": token.key,  # 保持向后兼容
                    "jwt": jwt_tokens,  # 新的JWT令牌
                    "message": "注册成功",
                },
                status=status.HTTP_201_CREATED,
            )

        except Exception:
            # 如果JWT创建失败，依然返回传统的Token
            return Response(
                {
                    "user": UserSerializer(user).data,
                    "token": token.key,
                    "message": "注册成功（使用Token认证）",
                    "warning": "JWT创建失败，使用Token认证",
                },
                status=status.HTTP_201_CREATED,
            )


class LoginView(APIView):
    """
    用户登录API视图

    验证用户凭据并返回JWT和Token双重认证令牌

    Endpoint: POST /api/accounts/login/
    Permission: AllowAny (公开接口)

    Request Body:
        username (str): 用户名
        password (str): 密码

    Response:
        200: 登录成功，返回用户信息和认证令牌
        401: 用户名或密码错误
        400: 请求数据验证失败
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request: Request) -> Response:
        """处理用户登录请求"""
        # 验证请求数据
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 提取登录凭据和请求信息
        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        ip_address: str = get_client_ip(request)
        user_agent: str = request.META.get("HTTP_USER_AGENT", "")

        # Django身份验证
        user: Optional[AbstractUser] = authenticate(
            username=username, password=password
        )

        if user is not None and user.is_active:
            # 获取或创建Django Token（向后兼容）
            token, _ = Token.objects.get_or_create(user=user)

            try:
                # 生成JWT令牌对
                jwt_tokens: Dict[str, Any] = create_jwt_for_user(user)

                # 记录成功登录事件
                log_security_event(
                    "user_login",
                    username=user.username,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )

                return Response(
                    {
                        "user": UserSerializer(user).data,
                        "token": token.key,  # Django Token（兼容性）
                        "jwt": jwt_tokens,  # JWT令牌对（推荐）
                        "message": "登录成功",
                    },
                    status=status.HTTP_200_OK,
                )

            except Exception as e:
                # JWT创建失败时的降级处理
                log_security_event(
                    "jwt_creation_failed",
                    username=user.username,
                    ip_address=ip_address,
                    details=str(e),
                )

                return Response(
                    {
                        "user": UserSerializer(user).data,
                        "token": token.key,
                        "message": "登录成功（使用Token认证）",
                        "warning": "JWT创建失败，使用Token认证",
                    },
                    status=status.HTTP_200_OK,
                )
        else:
            # 登录失败
            log_security_event(
                "login_failed",
                username=username,
                ip_address=ip_address,
                user_agent=user_agent,
                details="Invalid credentials",
            )

            return Response(
                {"error": "用户名或密码错误"}, status=status.HTTP_401_UNAUTHORIZED
            )


class LogoutView(APIView):
    """
    用户登出API视图

    处理用户登出，清理认证令牌并加入黑名单

    Endpoint: POST /api/accounts/logout/
    Permission: IsAuthenticated (需要认证)

    Headers:
        Authorization: Bearer <jwt_token> 或 Token <token>

    Request Body (可选):
        refresh_token (str): JWT刷新令牌，用于加入黑名单

    Response:
        200: 登出成功
        400: 登出过程中发生错误
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request) -> Response:
        try:
            user = request.user
            ip_address = get_client_ip(request)

            # 删除用户的Token（保持向后兼容）
            try:
                request.user.auth_token.delete()
            except Exception:
                pass  # Token可能不存在

            # 处理JWT刷新令牌黑名单
            refresh_token = request.data.get("refresh_token")
            if refresh_token:
                blacklist_result = blacklist_token(refresh_token)
                if not blacklist_result:
                    log_security_event(
                        "token_blacklist_failed",
                        username=user.username,
                        ip_address=ip_address,
                        details="Failed to blacklist refresh token",
                    )

            # 记录登出事件
            log_security_event(
                "user_logout", username=user.username, ip_address=ip_address
            )

            return Response({"message": "登出成功"}, status=status.HTTP_200_OK)

        except Exception as exc:
            return Response(
                {"error": f"登出失败: {str(exc)}"}, status=status.HTTP_400_BAD_REQUEST
            )


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
    Headers: Authorization: Bearer <jwt_token> 或 Token <token>
    Body: {
        "old_password": "OldPass123!",
        "new_password": "NewPass123!",
        "new_password2": "NewPass123!",
        "refresh_token": "<refresh_token>"  // 可选，用于JWT黑名单
    }
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Request) -> Response:
        """处理密码修改请求"""
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        ip_address = get_client_ip(request)

        # 验证旧密码
        if not user.check_password(serializer.validated_data["old_password"]):
            return Response({"error": "旧密码错误"}, status=status.HTTP_400_BAD_REQUEST)

        # 设置新密码
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        # 更新Token（保持向后兼容）
        Token.objects.filter(user=user).delete()
        new_token = Token.objects.create(user=user)

        # 处理JWT刷新令牌黑名单
        refresh_token = request.data.get("refresh_token")
        if refresh_token:
            blacklist_token(refresh_token)

        try:
            # 创廻新的JWT令牌
            new_jwt_tokens = create_jwt_for_user(user)

            # 记录密码修改事件
            log_security_event(
                "password_changed", username=user.username, ip_address=ip_address
            )

            return Response(
                {
                    "message": "密码修改成功",
                    "token": new_token.key,  # 保持向后兼容
                    "jwt": new_jwt_tokens,  # 新的JWT令牌
                },
                status=status.HTTP_200_OK,
            )

        except Exception:
            # JWT创廻失败，但密码修改成功
            return Response(
                {
                    "message": "密码修改成功",
                    "token": new_token.key,
                    "warning": "JWT创廻失败，请使用Token认证",
                },
                status=status.HTTP_200_OK,
            )
