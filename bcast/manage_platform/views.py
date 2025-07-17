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

from .models import Platform, GmailAccount, BlockedContact
from .serializers import PlatformSerializer, BlockedContactSerializer
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
            "redirect_uri": "https://api.jackdesk.com/platforms/gmail/oauth/callback",
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
                "token_expiry": timezone.now() + timedelta(seconds=expires_in),
                "active": True
            }
        )
        watch_gmail(account)
        response = HttpResponse("""
            <script>
              console.log("✅ Sending message to opener");
              if (window.opener) {
                window.opener.postMessage({ type: 'gmail-auth-success' }, '*');
              }
              window.close();
            </script>
        """, content_type='text/html')    
        # Remove COOP headers (dangerous if misused)
        response.headers['Cross-Origin-Opener-Policy'] = ''
        response.headers['Cross-Origin-Embedder-Policy'] = ''
        return response

class PlatformNotificationView(APIView):
    permission_classes = [EnterpriserUsers]  # Or IsAuthenticated
    def get(self, request, *args, **kwargs):
        user = request.user
        now = timezone.now()
        buffer_time = timedelta(days=1)
        # Get all Gmail platforms user has access to via orgs
        platforms = Platform.objects.filter(
            organization__enterprise_profiles__user=user,
            platform_name='gmail'
        ).distinct()
        notifications = []
        for platform in platforms:
            try:
                gmail_account = GmailAccount.objects.get(platform=platform)
            except GmailAccount.DoesNotExist:
                continue  # Skip platforms without Gmail accounts
            watch_expiry = gmail_account.watch_expiry
            token_expiry = gmail_account.token_expiry
            watch_expired = watch_expiry and now >= watch_expiry
            watch_warning = watch_expiry and (now + buffer_time >= watch_expiry) and not watch_expired
            token_expired = token_expiry and now >= token_expiry
            notifications.append({
                'platform_id': platform.id,
                'platform_name': platform.user_platform_name,
                'email': gmail_account.email_address,
                'watch_expiry': watch_expiry,
                'watch_expired': watch_expired,
                'watch_expiry_warning': watch_warning,
                'token_expiry': token_expiry,
                'token_expired': token_expired,
                'active': gmail_account.active
            })
        return Response(notifications)

class PlatformBlockedContactView(APIView):
    permission_classes = [EnterpriserUsers]
    def get_platform(self, platform_id, user):
        return get_object_or_404(
            Platform,
            id=platform_id,
            organization__enterprise_profiles__user=user  # or use platform.owner == user if applicable
        )
    def get(self, request, platform_id):
        platform = self.get_platform(platform_id, request.user)
        blocked_contacts = BlockedContact.objects.filter(platform=platform)
        serializer = BlockedContactSerializer(blocked_contacts, many=True)
        return Response(serializer.data)
    def post(self, request, platform_id):
        platform = self.get_platform(platform_id, request.user)
        data = request.data.copy()
        data['platform'] = platform.id
        serializer = BlockedContactSerializer(data=data)
        if serializer.is_valid():
            serializer.save(blocked_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self, request, platform_id):
        platform = self.get_platform(platform_id, request.user)
        contact_value = request.query_params.get("contact_value")
        if not contact_value:
            return Response({"detail": "Missing contact_value in query parameters."}, status=400)
        blocked = BlockedContact.objects.filter(platform=platform, contact_value=contact_value).first()
        if not blocked:
            return Response({"detail": "Blocked contact not found."}, status=404)
        blocked.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class BulkBlockContactView(APIView):
    permission_classes = [EnterpriserUsers]
    def post(self, request):
        platform_ids = request.data.get("platform_ids", [])
        contact_value = request.data.get("contact_value")
        contact_type = request.data.get("contact_type")
        reason = request.data.get("reason")
        if not all([platform_ids, contact_value, contact_type]):
            return Response({"detail": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)
        blocked_list = []
        for pid in platform_ids:
            try:
                platform = Platform.objects.get(
                    id=pid,
                    organization__enterprise_profiles__user=request.user
                )
            except Platform.DoesNotExist:
                continue
            blocked_contact = BlockedContact(
                platform=platform,
                contact_value=contact_value,
                contact_type=contact_type,
                reason=reason,
                blocked_by=request.user
            )
            blocked_list.append(blocked_contact)
        BlockedContact.objects.bulk_create(blocked_list)
        return Response({"blocked_count": len(blocked_list)}, status=status.HTTP_201_CREATED)

