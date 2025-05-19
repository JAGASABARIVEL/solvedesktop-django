# serializers.py
from rest_framework import serializers
from .models import KeyLogger
from django.conf import settings

class KeyLoggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = KeyLogger
        fields = ['id', 'organization', 'emp', 'date', 'app_details', 'idle_time']

    def create(self, validated_data):
        # Handle JSON dump for app_details
        app_details = validated_data.get('app_details')
        if isinstance(app_details, dict):
            validated_data['app_details'] = serializers.json.dumps(app_details)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Handle JSON dump for app_details
        app_details = validated_data.get('app_details')
        if isinstance(app_details, dict):
            validated_data['app_details'] = serializers.json.dumps(app_details)
        return super().update(instance, validated_data)
