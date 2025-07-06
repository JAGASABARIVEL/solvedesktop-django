import random, uuid
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.conf import settings
from django.utils.timezone import now
from django.core.cache import cache  # To store temporary tokens securely

from rest_framework.response import Response
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import (
    EnterpriseSerializer, EnterpriseOwnerRegistrationSerializer,
    EmployeeRegistrationSerializer, IndividualRegistrationSerializer,
    CustomUserSerializer, AgentRegistrationSerializer
)
from .permissions import NotLoggedIn, EnterpriserUsers
from .models import CustomUser, PasswordResetOTP, EnterpriseProfile, OwnerAccount
from manage_organization.models import Organization
from manage_files.models import FilePermission, File

# Create your views here.

from django.contrib.auth import get_user_model
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from django.conf import settings
from django.db import transaction

# Base Mixin to Filter by Organization
class OrganizationQuerysetMixin:
    def get_queryset(self):
        user_org = self.request.user.enterprise_profile.organization
        return super().get_queryset().filter(organization=user_org)

class EmployeeOwnerQueryMixin:
    def get_queryset(self):
        # Start from the queryset already filtered by organization
        queryset = super().get_queryset()
        # Filter EnterpriseProfile by linked user's user_type = 'employee'
        return queryset.filter(user__user_type__in=['employee', 'agent', 'owner'])

class AgentQuerysetMixin:
    def get_queryset(self):
        # Start from the queryset already filtered by organization
        queryset = super().get_queryset()
        # Filter EnterpriseProfile by linked user's user_type = 'agent'
        return queryset.filter(user__user_type='agent')


from manage_subscriptions.models import Subscription, UserSubscription

class GoogleLoginView(APIView):
    permission_classes = (NotLoggedIn,)
    def verify_and_update_subscription(self, user):
        existing_plans = None
        if user.user_type == "owner":
            existing_plans = ("manage_users", "manage_files", "manage_contacts", "manage_campaigns", "manage_conversations")
        elif user.user_type in ("individual", "employee"):# Individual and employee will have the same level of subscription
            existing_plans = ("manage_users", "manage_files")
        plan = None
        subscriptions_statuses = set()
        for plan_name in existing_plans:
            try:
                plan = Subscription.objects.get(app__app_name=plan_name)
            except Subscription.DoesNotExist:
                return Response({"error": "Invalid plan ID."}, status=status.HTTP_400_BAD_REQUEST)
            # Check for active or pending subscription
            existing_user_subscription = UserSubscription.objects.filter(user=user, plan=plan).first()
            if existing_user_subscription:
                subscriptions_statuses.add(existing_user_subscription.check_and_update_status())
                existing_user_subscription.save()
        return subscriptions_statuses

    def post(self, request):
        google_token = request.data.get("token")
        if not google_token:
            return Response({"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            # Verify the Google token
            google_info = id_token.verify_oauth2_token(
                google_token, google_requests.Request()
            )
            if google_info["aud"] not in [settings.GOOGLE_CLIENT_ID, settings.GOOGLE_DESKTOP_CLIENT_ID]:
                return Response({"error": f"Invalid audience: {google_info['aud']}"}, status=status.HTTP_400_BAD_REQUEST)
            # Extract user info from the Google response
            email = google_info.get("email")
            username = google_info.get("name")
            google_id = google_info.get("sub")  # Unique Google user ID
            if not email:
                return Response({"error": "Google account has no email"}, status=status.HTTP_400_BAD_REQUEST)
            # Check if the user already exists
            user, created = get_user_model().objects.get_or_create(
                email=email,
                defaults={"username": username, "is_active": True},
            )
            # Generate JWT token for authentication
            refresh = RefreshToken.for_user(user)
            enterprise_profile = getattr(user, "enterprise_profile", None)
            
            with transaction.atomic():
                subscriptions_statuses = self.verify_and_update_subscription(user)
                if isinstance(subscriptions_statuses, Response):
                    return subscriptions_statuses
                if len(subscriptions_statuses) > 1:
                    # It means we have other than 'active' statuses
                    user.is_subscription_complete = False
                    user.save()

            if enterprise_profile:
                organization = getattr(enterprise_profile, "organization", None)
                refresh["user_type"] = "ENTERPRISE"
                refresh["role"] = "frontend"
                refresh["service"] = "ui_main_client"
                refresh["guest"] = False
                refresh["organization_id"] = organization.id
                return Response({
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "image": google_info.get("picture"),
                        "username": user.username,
                        "is_registration_complete": user.is_registration_complete,
                        "is_subscription_complete": user.is_subscription_complete,
                        "is_payment_complete": user.is_payment_complete,
                        "is_productivity_enable": user.is_productivity_enable,
                        "role": "owner" if organization.owner == user else "employee",
                        "organization" : {
                            "id": organization.id,
                            "name": organization.name
                        }
                    },
                }, status=status.HTTP_200_OK)
            else:
                refresh["user_type"] = "INDIVIDUAL"
                refresh["role"] = "frontend"
                refresh["service"] = "ui_main_client"
                refresh["guest"] = False
                refresh["organization_id"] = -1
                return Response({
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "image": google_info.get("picture"),
                        "username": user.username,
                        "is_registration_complete": user.is_registration_complete,
                        "is_subscription_complete": user.is_subscription_complete,
                        "is_payment_complete": user.is_payment_complete,
                        "is_productivity_enable": user.is_productivity_enable,
                        "role": "individual",
                        "organization" : {
                            "id": -1,
                            "name": None
                        }
                    },
                }, status=status.HTTP_200_OK)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


# Updated Views
class EnterpriseOwnerRegistrationView(generics.CreateAPIView):
    permission_classes = (IsAuthenticated,)  # Ensure user is logged in via Google
    serializer_class = EnterpriseOwnerRegistrationSerializer
    def post(self, request, *args, **kwargs):
        user = request.user
        # Ensure the user hasn't already completed registration
        if user.is_registration_complete:
            return Response({"error": "Registration already completed."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            organization = Organization.objects.filter(
                owner=user,
                name=request.data["organization_name"]
            ).first()
            return Response(
                {
                    "message": "Enterprise owner registration completed successfully.",
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "user_type": user.user_type,
                        "organization": {
                            "id": organization.id,
                            "name": organization.name
                        },
                        "is_registration_complete": user.is_registration_complete,
                        "is_subscription_complete": user.is_subscription_complete,
                        "is_payment_complete": user.is_payment_complete,
                        "is_productivity_enable": user.is_productivity_enable,
                    },
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginPing(APIView):
    permission_classes = (IsAuthenticated,)
    def get(self, request):
        return Response({"status": "Success"}, status=status.HTTP_200_OK)

class EmployeeRegistrationView(generics.CreateAPIView):
    permission_classes = [EnterpriserUsers]  # Ensure user is logged in via Google
    serializer_class = EmployeeRegistrationSerializer

    def apply_permissions_to_children(self, parent_file, employee_user, can_read, can_write):
        """Recursively apply permissions to all child files/folders."""
        children = File.objects.filter(parent=parent_file, is_deleted=False)
        for child in children:
            permission, created = FilePermission.objects.update_or_create(
                file=child,
                user=employee_user,
                defaults={"can_read": can_read, "can_write": can_write, "inherited": True}
            )
            permission.save()
            # If the child is also a folder, apply to its children
            if child.is_folder():
                self.apply_permissions_to_children(child, employee_user, can_read, can_write)

    def post(self, request, *args, **kwargs):
        owner_user = request.user
        # Ensure only owners can register employees
        if owner_user.user_type != 'owner':
            return Response({"error": "Only owners can register employees."}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            employee_id = request.data.get("employee_id", None)
            employee_user = CustomUser.objects.filter(id=employee_id).first()
            if not employee_user:
                raise serializers.ValidationError("Cannot have employee field as empty")
            uname = owner_user.email.split("@")[0]
            org_name = owner_user.owned_org.name
            lookup_s3_key = f"{uname}/{org_name}/"
            file = File.objects.filter(s3_key=lookup_s3_key, owner=owner_user).first()
            if file:
                # Check if permission already exists and update instead of duplicating
                permission, created = FilePermission.objects.update_or_create(
                    file=file,
                    user=employee_user,
                    defaults={"can_read": True, "can_write": True}
                )
                permission.save()
                # If the file is a folder, apply permissions recursively
                if file.is_folder():
                    self.apply_permissions_to_children(file, employee_user, True, True)    
            return Response(
                {
                    "message": "Employee registration completed successfully.",
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AgentRegistrationView(generics.CreateAPIView):
    permission_classes = [EnterpriserUsers]  # Ensure user is logged in via Google
    serializer_class = AgentRegistrationSerializer
    def post(self, request, *args, **kwargs):
        user = request.user
        # Ensure only owners can register agents
        if user.user_type != 'owner':
            return Response({"error": "Only owners can register agents."}, status=status.HTTP_403_FORBIDDEN)
        serializer = self.get_serializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "message": "Employee registration completed successfully.",
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class IndividualRegistrationView(generics.CreateAPIView):
    permission_classes = (IsAuthenticated,)  # Ensure user is logged in via Google
    serializer_class = IndividualRegistrationSerializer
    def post(self, request, *args, **kwargs):
        user = request.user
        # Ensure the user hasn't already completed registration
        if user.is_registration_complete:
            return Response({"error": "Individual registration already completed."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            # Save individual user information
            serializer.save()
            return Response(
                {
                    "message": "Individual registration completed successfully.",
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "username": user.username,
                        "user_type": user.user_type,
                        "is_registration_complete": user.is_registration_complete,
                        "is_subscription_complete": user.is_subscription_complete,
                        "is_payment_complete": user.is_payment_complete,
                        "is_productivity_enable": user.is_productivity_enable,
                    },
                },
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Updated Login View
class LoginView(APIView):
    permission_classes = (NotLoggedIn,)
    def post(self, request):
        phone_number = request.data.get("phone_number")
        password = request.data.get("password")
        user = authenticate(request, phone_number=phone_number, password=password)
        if user:
            refresh = RefreshToken.for_user(user)
            enterprise_profile = getattr(user, "enterprise_profile", None)
            if enterprise_profile:
                organization = getattr(enterprise_profile, "organization", None)
                return Response({
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                    "user": {
                        "id": user.id,
                        "phone_number": user.phone_number,
                        "email": user.email,
                        "user_type": user.user_type,
                        "is_registration_complete": user.is_registration_complete,
                        "is_subscription_complete": user.is_subscription_complete,
                        "is_payment_complete": user.is_payment_complete,
                        "is_productivity_enable": user.is_productivity_enable,
                        "role": "owner" if organization.owner == user else "employee",
                        "organization" : {
                            "id": organization.id,
                            "name": organization.name
                        }
                    },
                })
            else:
                return Response({
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                    "user": {
                        "id": user.id,
                        "phone_number": user.phone_number,
                        "email": user.email,
                        "user_type": user.user_type,
                        "is_registration_complete": user.is_registration_complete,
                        "is_subscription_complete": user.is_subscription_complete,
                        "is_payment_complete": user.is_payment_complete,
                        "is_productivity_enable": user.is_productivity_enable,
                        "role": "individual",
                        "organization" : {
                            "id": -1,
                            "name": None
                        }
                    },
                })
        return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)


class UserListEnterpriseView(EmployeeOwnerQueryMixin, OrganizationQuerysetMixin, generics.ListAPIView):
    permission_classes = [EnterpriserUsers]
    queryset = EnterpriseProfile.objects.all()
    serializer_class = EnterpriseSerializer

class UserListAllView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    queryset = CustomUser.objects.all()
    serializer_class = CustomUserSerializer

class AgentListAllView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    queryset = CustomUser.objects.filter(user_type="agent").all()
    serializer_class = CustomUserSerializer

class AgentListEnterpriseView(AgentQuerysetMixin, OrganizationQuerysetMixin, generics.ListAPIView):
    permission_classes = [EnterpriserUsers]
    queryset = EnterpriseProfile.objects.all()
    serializer_class = EnterpriseSerializer


class LogoutView(APIView):
    permission_classes = (NotLoggedIn,)
    """User Logout API by blacklisting the refresh token"""
    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)
            token.blacklist()  # Blacklists the token
            return Response({"message": "Logged out successfully"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)


class RefreshTokenView(APIView):
    permission_classes = (NotLoggedIn,)
    """Refresh JWT access token using the refresh token"""
    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            refresh = RefreshToken(refresh_token)
            return Response({"access": str(refresh.access_token)}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": "Invalid refresh token"}, status=status.HTTP_400_BAD_REQUEST)


class RequestPasswordResetOTPView(generics.GenericAPIView):
    def post(self, request):
        email = request.data.get("email")
        user = CustomUser.objects.filter(email=email).first()
        if not user:
            return Response({"error": "User with this email does not exist."}, status=status.HTTP_400_BAD_REQUEST)
        # Check if an OTP exists and if resend limit is exceeded
        otp_record, created = PasswordResetOTP.objects.get_or_create(user=user)
        if not created and otp_record.is_blocked():
            return Response({"error": "Too many OTP requests. Try again in 24 hours."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        # Generate a new 6-digit OTP
        otp = str(random.randint(100000, 999999))
        otp_record.otp = otp
        otp_record.resend_count += 1  # Increase resend count
        otp_record.created_at = now()  # Reset timestamp
        otp_record.is_verified = False  # Reset verification status
        otp_record.save()
        # Send OTP via email
        send_mail(
            "Password Reset OTP",
            f"Your OTP for password reset is: {otp}. It expires in 5 minutes.",
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        return Response({"message": "OTP sent successfully."}, status=status.HTTP_200_OK)


class VerifyOTPView(generics.GenericAPIView):
    def post(self, request):
        email = request.data.get("email")
        otp = request.data.get("otp")
        user = CustomUser.objects.filter(email=email).first()
        if not user:
            return Response({"error": "Invalid email."}, status=status.HTTP_400_BAD_REQUEST)
        otp_record = PasswordResetOTP.objects.filter(user=user).first()
        if not otp_record or otp_record.is_expired():
            return Response({"error": "OTP has expired."}, status=status.HTTP_400_BAD_REQUEST)
        # Check if max attempts are reached
        if otp_record.attempts >= 3:
            return Response({"error": "Too many failed attempts. Try again in 24 hours."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if otp_record.otp != otp:
            otp_record.attempts += 1
            otp_record.save()
            return Response({"error": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)
        # OTP is correct → Mark as verified
        otp_record.is_verified = True
        otp_record.attempts = 0  # Reset attempts
        otp_record.save()
        # Generate a temporary token (valid for 15 minutes)
        reset_token = str(uuid.uuid4())  
        cache.set(f"password_reset_{user.id}", reset_token, timeout=900)  # Store token securely for 15 mins
        return Response({"message": "OTP verified successfully.", "reset_token": reset_token}, status=status.HTTP_200_OK)


class ResetPasswordView(generics.GenericAPIView):
    def post(self, request):
        phone_number = request.data.get("phone_number")
        reset_token = request.data.get("reset_token")
        new_password = request.data.get("new_password")
        user = CustomUser.objects.filter(phone_number=phone_number).first()
        if not user:
            return Response({"error": "Invalid phone."}, status=status.HTTP_400_BAD_REQUEST)
        # Validate the token from cache
        stored_token = cache.get(f"password_reset_{user.id}")
        if stored_token is None or stored_token != reset_token:
            return Response({"error": "Invalid or expired reset token."}, status=status.HTTP_400_BAD_REQUEST)
        # Reset the password
        user.set_password(new_password)
        user.save()
        # Invalidate the used reset token
        cache.delete(f"password_reset_{user.id}")
        return Response({"message": "Password reset successful."}, status=status.HTTP_200_OK)


class RemoveEmployeeView(generics.DestroyAPIView):
    permission_classes = [EnterpriserUsers]
    queryset = EnterpriseProfile.objects.all()
    serializer_class = EnterpriseSerializer

    def delete(self, request, *args, **kwargs):
        # Get the employee to remove
        profile = get_object_or_404(EnterpriseProfile, pk=kwargs["pk"])
        # Get owner’s organization
        try:
            owner = OwnerAccount.objects.get(user=request.user)
        except OwnerAccount.DoesNotExist:
            return Response({"detail": "Not an organization owner."}, status=status.HTTP_403_FORBIDDEN)
        if profile.organization != owner.organization:
            return Response({"detail": "You can only remove employees from your organization."},
                            status=status.HTTP_403_FORBIDDEN)
        # Removing all file permissions
        filepermissions = FilePermission.objects.filter(user=profile.user.id).all()
        for filepermission in filepermissions:
            filepermission.delete()
        # Changing the emplyoee role to individual
        profile.user.user_type = "individual"
        profile.user.save()
        # Removing from organization
        profile.delete()  # This will only delete the enterprise profile
        return Response({"detail": "Employee removed."}, status=status.HTTP_204_NO_CONTENT)

class RemoveAgentView(generics.DestroyAPIView):
    permission_classes = [EnterpriserUsers]
    queryset = EnterpriseProfile.objects.all()
    serializer_class = EnterpriseSerializer

    def delete(self, request, *args, **kwargs):
        # Get the employee to remove
        profile = get_object_or_404(EnterpriseProfile, pk=kwargs["pk"])
        # Get owner’s organization
        try:
            owner = OwnerAccount.objects.get(user=request.user)
        except OwnerAccount.DoesNotExist:
            return Response({"detail": "Not an organization owner."}, status=status.HTTP_403_FORBIDDEN)
        if profile.organization != owner.organization:
            return Response({"detail": "You can only remove agent from your organization."},
                            status=status.HTTP_403_FORBIDDEN)
        profile.user.delete()  # This will also delete the related EnterpriseProfile due to cascade
        return Response({"detail": "Agent removed."}, status=status.HTTP_204_NO_CONTENT)


# views.py
import jwt
from datetime import datetime, timedelta

class GuestJWTView(APIView):
    authentication_classes = []  # No auth required
    permission_classes = []      # Allow all
    def post(self, request):
        organization_id = request.data.get("organization")
        payload = {
            "user_type": "GUEST",
            "role": "frontend",
            "service": "ui_chat_widget_client",
            "guest": True,
            "user_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "exp": datetime.utcnow() + timedelta(minutes=60),
            "iat": datetime.utcnow(),
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
        return Response({"access": token}, status=status.HTTP_201_CREATED)
