# -*- coding: utf-8 -*-
"""
SmartPaste JWT 鉴权工具模块
提供 JWT 令牌生成、验证、用户认证等功能
同时支持传统的 Django Token 认证以保持兼容性
"""

import base64
import datetime
import logging
from functools import wraps

import jwt
import scrypt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import (
    JWTAuthentication as BaseJWTAuthentication,
)

User = get_user_model()
logger = logging.getLogger(__name__)


class JWTAuthError(Exception):
    """JWT认证异常"""

    pass


def generate_jwt(payload, expiry=None):
    """
    生成JWT令牌
    :param payload: dict 载荷
    :param expiry: datetime 有效期
    :return: JWT字符串
    """
    if expiry is None:
        now = datetime.datetime.utcnow()  # 使用UTC时间
        expire_hours = getattr(settings, "JWT_EXPIRE_HOURS", 24)
        if expire_hours <= 0:
            expire_hours = 24
        expiry = now + datetime.timedelta(hours=expire_hours)

    # 构建标准的JWT载荷
    _payload = {
        "exp": expiry,
        "iat": datetime.datetime.utcnow(),  # 签发时间
        "nbf": datetime.datetime.utcnow(),  # 生效时间
        "iss": "SmartPaste-Web",  # 签发者
    }
    _payload.update(payload)

    secret = getattr(settings, "JWT_SECRET", settings.SECRET_KEY)

    try:
        token = jwt.encode(_payload, secret, algorithm="HS256")
        logger.info(f"JWT token generated for user: {payload.get('user_id')}")
        return token
    except Exception as e:
        logger.error(f"JWT generation failed: {e}")
        raise JWTAuthError("Token generation failed")


def verify_jwt(token):
    """
    验证JWT令牌
    :param token: JWT字符串
    :return: dict payload 或 None
    """
    if not token:
        return None

    # 移除Bearer前缀
    if token.startswith("Bearer "):
        token = token[7:]

    secret = getattr(settings, "JWT_SECRET", settings.SECRET_KEY)

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
            },
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
        return None
    except Exception as e:
        logger.error(f"JWT verification failed: {e}")
        return None


def encrypt_password(password):
    """
    密码加密
    :param password: 明文密码
    :return: 加密后的密码
    """
    if not password:
        raise ValueError("Password cannot be empty")

    salt = getattr(settings, "SALT", settings.SECRET_KEY[:16].encode("utf-8"))
    if isinstance(salt, str):
        salt = salt.encode("utf-8")

    try:
        key = scrypt.hash(password.encode("utf-8"), salt, 32768, 8, 1, 32)
        return base64.b64encode(key).decode("ascii")
    except Exception as e:
        logger.error(f"Password encryption failed: {e}")
        raise ValueError("Password encryption failed")


def get_user_by_id(user_id):
    """
    根据用户ID获取用户对象
    :param user_id: 用户ID
    :return: (user, result) 元组
    """
    try:
        user = User.objects.get(id=user_id, is_active=True)
        return user, True
    except User.DoesNotExist:
        logger.warning(f"User not found: {user_id}")
        return None, False
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return None, False


def jwt_authentication(request):
    """
    JWT认证函数 - 从请求头中验证JWT令牌并设置用户
    :param request: Django request 对象
    """
    request.user = None

    # 检查Authorization头
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")

    if not auth_header:
        return

    try:
        # 支持Bearer和Token两种格式
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        elif auth_header.startswith("Token "):
            # 如果是Token格式，则跳过JWT认证，让TokenAuthentication处理
            return
        else:
            token = auth_header

        payload = verify_jwt(token)
        if payload:
            user_id = payload.get("user_id")
            if user_id:
                user, result = get_user_by_id(user_id)
                if result and user:
                    request.user = user
                    logger.debug(f"User authenticated via JWT: {user_id}")
                else:
                    logger.warning(f"JWT auth failed - user not found: {user_id}")
            else:
                logger.warning("JWT auth failed - no user_id in payload")
        else:
            logger.debug("JWT auth failed - invalid token")

    except Exception as e:
        logger.error(f"JWT authentication error: {e}")


def login_required(func):
    """
    登录必需装饰器
    使用方法：放在 method_decorators 中或直接装饰视图方法
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # 判断第一个参数是否是请求对象
            request = args[0] if args else None

            # 对于类方法，第二个参数才是request
            if hasattr(args[0], "__class__") and len(args) > 1:
                request = args[1]

            if not request or not hasattr(request, "META"):
                # 无法获取request对象，直接执行函数
                return func(*args, **kwargs)

            # 执行JWT认证
            jwt_authentication(request)

            if (
                not hasattr(request, "user")
                or not request.user
                or not request.user.is_authenticated
            ):
                # 返回错误响应需要动态导入以避免循环导入
                from rest_framework.response import Response

                return Response(
                    {
                        "error": "Authentication required",
                        "message": "用户必须登录",
                        "code": "UNAUTHORIZED",
                    },
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            return func(*args, **kwargs)

        except Exception as e:
            logger.error(f"Login required decorator error: {e}")
            from rest_framework.response import Response

            return Response(
                {
                    "error": "Authentication error",
                    "message": "认证过程中发生错误",
                    "code": "AUTH_ERROR",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    return wrapper


class JWTAuthentication(BaseJWTAuthentication):
    """
    自定义JWT认证类，继承自rest_framework_simplejwt
    支持自定义的JWT令牌格式
    """

    def authenticate(self, request):
        # 首先尝试自定义JWT认证
        auth_header = self.get_header(request)
        if auth_header is None:
            return None

        raw_token = self.get_raw_token(auth_header)
        if raw_token is None:
            return None

        # 尝试使用自定义的JWT验证
        try:
            payload = verify_jwt(raw_token.decode("utf-8"))
            if payload:
                user_id = payload.get("user_id")
                if user_id:
                    user, result = get_user_by_id(user_id)
                    if result and user:
                        return (user, raw_token)
        except Exception as e:
            logger.debug(f"Custom JWT auth failed: {e}")

        # 如果自定义验证失败，尝试标准的simplejwt验证
        try:
            return super().authenticate(request)
        except Exception as e:
            logger.debug(f"Standard JWT auth failed: {e}")
            return None


class SmartPasteRefreshToken(RefreshToken):
    """
    自定义的刷新令牌类
    """

    @classmethod
    def for_user(cls, user):
        """
        为用户创建刷新令牌
        """
        token = super().for_user(user)

        # 添加自定义声明
        token["username"] = user.username
        token["email"] = user.email
        token["user_type"] = "smartpaste_user"

        logger.info(f"Refresh token created for user: {user.username}")
        return token


def create_jwt_for_user(user):
    """
    为用户创建JWT令牌对（访问令牌+刷新令牌）
    :param user: User对象
    :return: dict 包含access和refresh令牌
    """
    try:
        # 使用自定义的刷新令牌
        refresh = SmartPasteRefreshToken.for_user(user)

        # 同时生成自定义格式的JWT（保持向后兼容）
        custom_payload = {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
        }
        custom_jwt = generate_jwt(custom_payload)

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "custom_jwt": custom_jwt,  # 自定义格式的JWT
            "expires_in": 86400,  # 24小时
            "token_type": "Bearer",
        }
    except Exception as e:
        logger.error(f"Error creating JWT for user {user.username}: {e}")
        raise JWTAuthError("Failed to create JWT tokens")


def blacklist_token(refresh_token):
    """
    将刷新令牌加入黑名单
    :param refresh_token: 刷新令牌字符串
    """
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
        logger.info("Refresh token blacklisted successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to blacklist token: {e}")
        return False


def get_client_ip(request):
    """
    获取客户端真实IP地址
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "unknown")
    return ip


def log_security_event(
    event_type, username=None, ip_address=None, user_agent=None, details=None
):
    """
    记录安全事件
    """
    log_message = f"Security Event: {event_type}"
    if username:
        log_message += f" | User: {username}"
    if ip_address:
        log_message += f" | IP: {ip_address}"
    if details:
        log_message += f" | Details: {details}"

    logger.info(log_message)


# 为了保持向后兼容性，保留原有的函数接口
def jwt_required(view_func):
    """
    JWT必需装饰器（别名）
    """
    return login_required(view_func)
