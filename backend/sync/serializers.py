# sync/serializers.py
from rest_framework import serializers
from .models import UserConfig, ClipboardFile

class UserConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserConfig
        fields = ['file', 'updated_at']

class ClipboardFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClipboardFile
        fields = ['id', 'file', 'relative_path', 'created_at']
        read_only_fields = ['created_at']