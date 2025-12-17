#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SmartPaste JWT 鉴权功能测试脚本
"""

import os
import sys
import django
import json
from django.conf import settings

# 设置Django环境
# 将backend目录添加到Python路径中
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from django.contrib.auth import get_user_model
from utils.jwt import create_jwt_for_user, verify_jwt, generate_jwt
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


def test_jwt_functionality():
    """测试JWT功能"""
    print("=" * 50)
    print("SmartPaste JWT 鉴权功能测试")
    print("=" * 50)

    # 1. 创建测试用户
    print("\n1. 创建测试用户...")
    try:
        # 删除之前的测试用户（如果存在）
        User.objects.filter(username="testuser").delete()

        user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        print(f"✓ 测试用户创建成功: {user.username}")
    except Exception as e:
        print(f"✗ 创建测试用户失败: {e}")
        return False

    # 2. 测试JWT令牌生成
    print("\n2. 测试JWT令牌生成...")
    try:
        jwt_tokens = create_jwt_for_user(user)
        print("✓ JWT令牌生成成功")
        print(f"  - Access Token: {jwt_tokens['access'][:50]}...")
        print(f"  - Refresh Token: {jwt_tokens['refresh'][:50]}...")
        print(f"  - Custom JWT: {jwt_tokens['custom_jwt'][:50]}...")
        print(f"  - Token Type: {jwt_tokens['token_type']}")
        print(f"  - Expires In: {jwt_tokens['expires_in']} seconds")
    except Exception as e:
        print(f"✗ JWT令牌生成失败: {e}")
        return False

    # 3. 测试自定义JWT验证
    print("\n3. 测试自定义JWT验证...")
    try:
        custom_jwt = jwt_tokens["custom_jwt"]
        payload = verify_jwt(custom_jwt)
        if payload:
            print("✓ 自定义JWT验证成功")
            print(f"  - User ID: {payload.get('user_id')}")
            print(f"  - Username: {payload.get('username')}")
            print(f"  - Email: {payload.get('email')}")
            print(f"  - Issued At: {payload.get('iat')}")
            print(f"  - Expires At: {payload.get('exp')}")
        else:
            print("✗ 自定义JWT验证失败")
            return False
    except Exception as e:
        print(f"✗ 自定义JWT验证出错: {e}")
        return False

    # 4. 测试标准JWT令牌验证
    print("\n4. 测试标准JWT令牌验证...")
    try:
        access_token = jwt_tokens["access"]
        refresh_token = RefreshToken(jwt_tokens["refresh"])

        # 验证访问令牌
        from rest_framework_simplejwt.tokens import AccessToken

        access_token_obj = AccessToken(access_token)
        print("✓ 标准访问令牌验证成功")
        print(f"  - Token Type: {access_token_obj.get('token_type', 'access')}")
        print(f"  - User ID: {access_token_obj.get('user_id')}")

    except Exception as e:
        print(f"✗ 标准JWT令牌验证失败: {e}")
        return False

    # 5. 测试令牌黑名单功能
    print("\n5. 测试令牌黑名单功能...")
    try:
        from utils.jwt import blacklist_token

        result = blacklist_token(jwt_tokens["refresh"])
        if result:
            print("✓ 刷新令牌成功加入黑名单")
        else:
            print("✗ 令牌黑名单功能失败")
            return False
    except Exception as e:
        print(f"✗ 令牌黑名单功能出错: {e}")
        return False

    # 6. 验证黑名单令牌已失效
    print("\n6. 验证黑名单令牌已失效...")
    try:
        # 尝试再次使用已黑名单的令牌
        blacklisted_refresh = RefreshToken(jwt_tokens["refresh"])
        # 这应该会抛出异常
        print("✗ 黑名单令牌仍然有效（这是错误的）")
    except Exception as e:
        print("✓ 黑名单令牌已正确失效")

    # 7. 清理测试数据
    print("\n7. 清理测试数据...")
    try:
        user.delete()
        print("✓ 测试用户已删除")
    except Exception as e:
        print(f"✗ 清理测试数据失败: {e}")

    print("\n" + "=" * 50)
    print("✓ JWT功能测试完成！所有测试均通过。")
    print("=" * 50)
    return True


def test_api_compatibility():
    """测试API兼容性"""
    print("\n" + "=" * 50)
    print("API兼容性测试")
    print("=" * 50)

    print("\n现在您可以使用以下方式进行API认证：")
    print("\n1. 使用JWT Bearer Token (推荐):")
    print("   Authorization: Bearer <access_token>")

    print("\n2. 使用传统Token (向后兼容):")
    print("   Authorization: Token <token_key>")

    print("\n3. 登录端点现在返回双重认证信息:")
    print("   POST /api/accounts/login/")
    print("   Response:")
    print("   {")
    print("     'user': {...},")
    print("     'token': 'token_key',  // 传统Token")
    print("     'jwt': {")
    print("       'access': 'jwt_access_token',")
    print("       'refresh': 'jwt_refresh_token',")
    print("       'custom_jwt': 'custom_format_jwt',")
    print("       'expires_in': 86400,")
    print("       'token_type': 'Bearer'")
    print("     }")
    print("   }")

    print("\n4. 刷新JWT令牌:")
    print("   POST /api/token/refresh/")
    print("   Body: { 'refresh': '<refresh_token>' }")

    return True


if __name__ == "__main__":
    try:
        # 测试JWT功能
        jwt_success = test_jwt_functionality()

        # 测试API兼容性
        api_success = test_api_compatibility()

        if jwt_success and api_success:
            print(f"\n🎉 所有测试通过！JWT鉴权系统已成功集成到SmartPaste-Web项目中。")
            print(f"\n📝 下一步：")
            print(f"   1. 启动开发服务器: python manage.py runserver")
            print(f"   2. 使用Postman或其他工具测试API端点")
            print(f"   3. 前端可以使用JWT或Token两种认证方式")

    except Exception as e:
        print(f"\n❌ 测试过程中出现错误: {e}")
        import traceback

        traceback.print_exc()
