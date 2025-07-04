from django.shortcuts import get_object_or_404

from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Platform
from .serializers import PlatformSerializer
from .permissions import IsOwnerOrPrivileged
from manage_users.permissions import EnterpriserUsers

from VendorApi.Whatsapp.message import TemplateMessage

class PlatformListCreateView(generics.ListCreateAPIView):
    serializer_class = PlatformSerializer
    permission_classes = [EnterpriserUsers]

    def get_queryset(self):
        user = self.request.user
        # Fetch platforms for organizations the user belongs to
        queryset = Platform.objects.filter(organization__enterprise_profiles__user=user)
        # Optional query parameter: platform_type
        platform_type = self.request.query_params.get('platform_type')
        if platform_type:
            queryset = queryset.filter(platform_name=platform_type)
        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        enterprise_profile = getattr(user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        # Check if user is the owner or privileged in this specific organization
        if not (organization.owner == user or organization.enterprise_profiles.filter(user=user).exists()):
            raise permissions.PermissionDenied("You do not have permission to add platforms.")
        serializer.save(owner=user)

class PlatformRetrieveUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PlatformSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrPrivileged]

    def get_queryset(self):
        user = self.request.user
        return Platform.objects.filter(organization__enterprise_profiles__user=user)


class PlatformTemplateAPIView(APIView):
    permission_classes = [EnterpriserUsers]

    def get(self, request, platform_id):
        # Ensure the platform exists and user has access
        platform = get_object_or_404(Platform, id=platform_id, organization__enterprise_profiles__user=request.user)

        # Validate user's access rights
        organization = platform.organization
        if not (organization.owner == request.user or organization.enterprise_profiles.filter(user=request.user).exists()):
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        # Fetch WhatsApp templates
        approved_templates = TemplateMessage(
            waba_id=platform.app_id,
            phone_number_id=platform.login_id,
            token=platform.login_credentials
        )

        response = approved_templates.get_templates().json()

        return Response({"whatsapp": response.get("data", [])}, status=status.HTTP_200_OK)
