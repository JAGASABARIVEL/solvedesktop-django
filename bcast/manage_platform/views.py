import requests
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.http import HttpResponse

from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response

from manage_users.permissions import EnterpriserUsers
from manage_email.gmail_utils import watch_gmail, poll_history

from VendorApi.Whatsapp.message import TemplateMessage

from .models import Platform, GmailAccount
from .serializers import PlatformSerializer
from .permissions import IsOwnerOrPrivileged

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


class GmailOAuthCallback(APIView):
    permission_classes = []  # Ensure user is logged in via Google
    authentication_classes = []
    def get(self, request):
        code = request.GET.get("code")
        platform_id = request.GET.get("state")
        if not code:
            return Response({"error": "Missing code"}, status=400)
        if not platform_id:
            return Response({"error": "Missing platform_id"}, status=400)
        platform = get_object_or_404(Platform, id=platform_id)
        # Exchange code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": "http://127.0.0.1:8000/platforms/gmail/oauth/callback",
            "grant_type": "authorization_code"
        }
        token_response = requests.post(token_url, data=data)
        token_data = token_response.json()
        if "error" in token_data or "access_token" not in token_data:
            return Response({"error": "Failed to exchange token", "details": token_data}, status=400)
        print("token_data ", token_data)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        # Get email
        user_info = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        ).json()
        print("user_info ", user_info)
        email = user_info.get("email")
        if not email:
            return Response({"error": "Failed to fetch email address"}, status=400)
        # Upsert GmailAccount using platform
        account, created = GmailAccount.objects.update_or_create(
            platform_id=platform.id,
            defaults={
                "email_address": email,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_expiry": timezone.now() + timedelta(seconds=expires_in)
            }
        )
        # Optional: Watch Gmail right here
        watch_gmail(account)
        #return Response({
        #    "message": "Gmail connected successfully",
        #    "email": email,
        #    "created": created
        #})
        return HttpResponse("""
                            <script>
                            window.close();
                            </script>
                            <p>You can now close this window.</p>
                            """
                            )


class PollHistory(APIView):
    permission_classes = []  # Ensure user is logged in via Google
    authentication_classes = []
    def get(self, request):
        account = GmailAccount.objects.filter(email_address='kjagasabarivel@gmail.com').first()
        poll_history(account)
        return Response({"message": "Gmail polled successfully"})