from django.db import models
from django.conf import settings

class AppUsage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    system = models.CharField(max_length=255, default='Default System')  # NEW
    event_id = models.IntegerField(default=-1)
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
        return f"{self.user} - {self.system} - {self.app_name} - {self.duration}s"

    class Meta:
        unique_together = ('user', 'system', 'event_id')


class AFKEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    system = models.CharField(max_length=255, default='Default System')  # NEW
    event_id = models.IntegerField(default=-1)
    start_time = models.DateTimeField()
    duration = models.FloatField(help_text="Duration in seconds")
    is_afk = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.system} - {'AFK' if self.is_afk else 'Active'} - {self.duration}s"

    class Meta:
        unique_together = ('user', 'system', 'event_id')
