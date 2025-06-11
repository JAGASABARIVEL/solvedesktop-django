from django.db import models
from django.conf import settings


class AppUsage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    app_name = models.CharField(max_length=255)
    window_title = models.TextField()
    start_time = models.DateTimeField()
    duration = models.FloatField(help_text="Duration in seconds")
    created_at = models.DateTimeField(auto_now_add=True)

    class ProductivityType(models.TextChoices):
        PRODUCTIVE = "productive"
        UNPRODUCTIVE = "unproductive"
        NEUTRAL = "neutral"

    productivity_tag = models.CharField(
        max_length=20,
        choices=ProductivityType.choices,
        default=ProductivityType.NEUTRAL
    )

    def __str__(self):
        return f"{self.user} - {self.app_name} - {self.duration}s"

class AFKEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    start_time = models.DateTimeField()
    duration = models.FloatField(help_text="Duration in seconds")
    is_afk = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {'AFK' if self.is_afk else 'Active'} - {self.duration}s"
