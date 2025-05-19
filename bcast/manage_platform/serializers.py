from rest_framework import serializers
from .models import Platform

class PlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform
        fields = ['id', 'platform_name', 'user_platform_name', 'login_id', 'app_id', 'login_credentials', "secret_key", 'organization', 'owner', 'status']
        extra_kwargs = {
            'organization': {'read_only': True},  # Mark organization as read-only
        }

    def validate(self, data):
        request = self.context['request']
        user = request.user
        enterprise_profile = getattr(user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)

        # Ensure user is owner or has privilege access to create
        if request.method == 'POST':
            data['organization'] = organization
        return data
