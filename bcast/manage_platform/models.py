from django.db import models
from django.conf import settings
from django.utils import timezone

# Create your models here.
class Platform(models.Model):
    PLATFORM_CHOICES = [('whatsapp', 'WhatsApp'), ('messenger', 'Messenger'), ('telegram', 'Telegram'), ('gmail', 'Gmail'), ('webchat', 'Webchat')]

    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE, related_name='platforms')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='platforms')
    platform_name = models.TextField(choices=PLATFORM_CHOICES)
    user_platform_name = models.TextField()
    login_id = models.TextField()
    app_id = models.TextField()
    login_credentials = models.TextField()
    secret_key = models.TextField()
    status = models.TextField(default='active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['organization', 'user_platform_name'], name='unique_user_platform_per_org')
        ]


class GmailAccount(models.Model):
    platform = models.OneToOneField(settings.PLATFORM_MODEL, on_delete=models.CASCADE, related_name='gmail_account')
    email_address = models.EmailField(unique=True)
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()
    watch_expiry = models.DateTimeField(null=True, blank=True)
    history_id = models.CharField(max_length=255, null=True, blank=True)
    last_watch_time = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    @property
    def is_token_expired(self):
        return timezone.now() >= self.token_expiry


class ProcessedGmailMessage(models.Model):
    gmail_account = models.ForeignKey(GmailAccount, on_delete=models.CASCADE, related_name='processed_messages')
    message_id = models.CharField(max_length=255, unique=True)
    processed_at = models.DateTimeField(auto_now_add=True)


class BlockedContact(models.Model):
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name='blocked_contacts')
    contact_value = models.TextField(help_text="Phone number or email address to block")
    contact_type = models.CharField(max_length=20, choices=[('whatsapp', 'WhatsApp'), ('messenger', 'Messenger'), ('telegram', 'Telegram'), ('gmail', 'Gmail'), ('webchat', 'Webchat')])
    reason = models.TextField(blank=True, null=True)
    blocked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    blocked_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ('platform', 'contact_value')
        indexes = [
            models.Index(fields=['platform', 'contact_value']),
        ]
    def __str__(self):
        return f"{self.contact_value} blocked on {self.platform.user_platform_name}"

