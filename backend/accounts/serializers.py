from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """用户信息序列化器"""

    # 显式声明 avatar，确保返回绝对路径 (http://domain.com/media/...)
    avatar = serializers.ImageField(read_only=True, use_url=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "phone", "avatar", "created_at", "bio"]
        read_only_fields = ["id", "created_at"]


class RegisterSerializer(serializers.ModelSerializer):
    """用户注册序列化器"""

    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={"input_type": "password"},
    )
    password2 = serializers.CharField(
        write_only=True, required=True, style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = ["username", "email", "password", "password2", "phone"]

    def validate(self, attrs):
        """验证两次密码是否一致"""
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password": "两次密码不一致"})
        return attrs

    def validate_email(self, value):
        """验证邮箱是否已存在"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("该邮箱已被注册")
        return value

    def create(self, validated_data):
        """创建用户"""
        validated_data.pop("password2")
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            phone=validated_data.get("phone", ""),
        )
        return user


class EncryptionKeySerializer(serializers.ModelSerializer):
    """E2EE 密钥管理序列化器"""

    class Meta:
        model = User
        fields = ["kdf_salt", "encrypted_dek", "kdf_iterations", "kdf_algorithm"]
        extra_kwargs = {
            "kdf_iterations": {"required": False},
            "kdf_algorithm": {"required": False},
        }


class LoginSerializer(serializers.Serializer):
    """用户登录序列化器"""

    username = serializers.CharField(required=True)
    password = serializers.CharField(
        required=True, write_only=True, style={"input_type": "password"}
    )


class ChangePasswordSerializer(serializers.Serializer):
    """修改密码序列化器"""

    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(
        required=True, write_only=True, validators=[validate_password]
    )
    new_password2 = serializers.CharField(required=True, write_only=True)

    def validate(self, attrs):
        """验证两次新密码是否一致"""
        if attrs["new_password"] != attrs["new_password2"]:
            raise serializers.ValidationError({"new_password": "两次密码不一致"})
        return attrs


class AvatarUploadSerializer(serializers.ModelSerializer):
    """
    专门用于上传头像的序列化器
    """

    avatar = serializers.ImageField(required=True)

    class Meta:
        model = User
        fields = ["avatar"]

    def update(self, instance, validated_data):
        # 这里的逻辑很简单，就是覆盖原有的 avatar
        instance.avatar = validated_data["avatar"]
        instance.save()
        return instance
