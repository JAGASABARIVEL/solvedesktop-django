from rest_framework import serializers
from .models import AppUsage, AFKEvent

class AppUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppUsage
        fields = '__all__'

class AFKEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AFKEvent
        fields = '__all__'
