from django.db import models
from django.conf import settings

# Create your models here.
class Platform(models.Model):
    PLATFORM_CHOICES = [('whatsapp', 'WhatsApp'), ('telegram', 'Telegram'), ('gmail', 'Gmail'), ('webchat', 'Webchat')]

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
