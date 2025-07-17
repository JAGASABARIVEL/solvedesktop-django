from rest_framework import serializers
from .models import Platform, BlockedContact

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

class BlockedContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlockedContact
        fields = ['id', 'platform', 'contact_value', 'contact_type', 'reason', 'blocked_at']
        read_only_fields = ['id', 'blocked_at']

