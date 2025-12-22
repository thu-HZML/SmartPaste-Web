from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import (
    UserAttributeSimilarityValidator as DjangoUserAttributeSimilarityValidator,
    MinimumLengthValidator as DjangoMinimumLengthValidator,
    CommonPasswordValidator as DjangoCommonPasswordValidator,
    NumericPasswordValidator as DjangoNumericPasswordValidator,
)


class CustomMinimumLengthValidator(DjangoMinimumLengthValidator):
    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                f"密码长度不足，至少需要 {self.min_length} 个字符。",
                code="password_too_short",
            )


class CustomNumericPasswordValidator(DjangoNumericPasswordValidator):
    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                "密码不能仅由数字组成，请包含字母或特殊符号。",
                code="password_entirely_numeric",
            )


class CustomUserAttributeSimilarityValidator(DjangoUserAttributeSimilarityValidator):
    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                "密码与您的个人信息（如用户名）过于相似，请尝试其他密码。",
                code="password_too_similar",
            )


class CustomCommonPasswordValidator(DjangoCommonPasswordValidator):
    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError:
            raise ValidationError(
                "该密码过于常见，容易被猜到，请使用更复杂的密码。",
                code="password_too_common",
            )
