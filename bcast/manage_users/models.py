from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.conf import settings


# Create your models here.
from django.utils.timezone import now, timedelta


class CustomUserManager(BaseUserManager):
    def create_user(self, phone_number, password=None, **extra_fields):
        """Create and return a regular user with a phone number as the username."""
        if not phone_number:
            raise ValueError("The phone number is required")

        extra_fields.setdefault("is_active", True)
        user = self.model(phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, password=None, **extra_fields):
        """Create and return a superuser."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(phone_number, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    USER_TYPE_CHOICES = (
        ('individual', 'Individual'),
        ('employee', 'Employee'),
        ('owner', 'Owner'),
        ('agent', 'Agent')
    )
    email = models.EmailField(unique=True, null=True, blank=True)
    phone_number = models.TextField(unique=True, null=True, blank=True)
    username = models.TextField(blank=True, null=True)

    # User type & status tracking
    user_type = models.TextField(choices=USER_TYPE_CHOICES, default='individual')
    is_registration_complete = models.BooleanField(default=False)
    is_subscription_complete = models.BooleanField(default=False)
    is_payment_complete = models.BooleanField(default=False)

    # Permissions
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    USERNAME_FIELD = "phone_number"
    REQUIRED_FIELDS = ["email"]

    objects = CustomUserManager()

    def __str__(self):
        return self.phone_number or self.email


class EnterpriseProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enterprise_profile")
    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE, related_name="enterprise_profiles")
    uuid = models.TextField(blank=True, null=True)
    is_privileged = models.BooleanField(default=False)
    def __str__(self):
        return f"Enterprise Profile of {self.user}"


class OwnerAccount(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owner_profile")
    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PasswordResetOTP(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    otp = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    resend_count = models.IntegerField(default=0)

    def is_expired(self):
        return (now() - self.created_at) > timedelta(minutes=5)

    def is_blocked(self):
        return (self.attempts >= 3 or self.resend_count >= 3) and (now() - self.created_at) < timedelta(hours=24)

    def __str__(self):
        return f"OTP for {self.user.email} - {self.otp} (Verified: {self.is_verified})"
