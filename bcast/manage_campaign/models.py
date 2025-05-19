from django.db import models
from django.conf import settings
from django.utils.timezone import now


# Create your models here.

class ScheduledMessage(models.Model):
    name = models.TextField()
    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE, related_name='scheduled_messages')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='scheduled_messages')

    RECIPIENT_TYPE_CHOICES = [
        ('individual', 'Individual'),
        ('group', 'Group')
    ]
    recipient_type = models.TextField(choices=RECIPIENT_TYPE_CHOICES)
    recipient_id = models.IntegerField()  # Contact ID or Group ID

    frequency = models.IntegerField(default=-1)
    message_body = models.TextField()
    platform = models.ForeignKey(settings.PLATFORM_MODEL, on_delete=models.CASCADE, related_name='scheduled_messages')
    scheduled_time = models.DateTimeField()
    datasource = models.JSONField(blank=True, null=True)
    excel_filename = models.TextField(blank=True, null=True)

    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('warning', 'Warning'),
        ('scheduled_warning', 'Scheduled Warning'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ]
    status = models.TextField(choices=STATUS_CHOICES, default='scheduled')

    MSG_STATUS_CHOICES = [
        ('', 'Pending'),
        ('sent_to_server', 'Sent to Server'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('sent', 'Sent'),
        ('failed', 'Failed')
    ]
    msg_status = models.TextField(choices=MSG_STATUS_CHOICES, blank=True, default='')

    sent_time = models.DateTimeField(blank=True, null=True)
    messageid = models.TextField(blank=True, null=True)
    template = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('name', 'organization')

    def __str__(self):
        return self.name


class PlatformLog(models.Model):
    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE)
    recipient = models.ForeignKey(settings.CONTACT_MODEL, on_delete=models.CASCADE)
    scheduled_message = models.ForeignKey('ScheduledMessage', on_delete=models.CASCADE)
    log_message = models.TextField(blank=True, null=True)
    messageid = models.TextField(blank=True, null=True, default=None)
    status = models.TextField(default='success')
    created_at = models.DateTimeField(default=now)

    def __str__(self):
        return f"Log: {self.log_message} - Status: {self.status}"
