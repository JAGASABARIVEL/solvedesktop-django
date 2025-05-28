from django.db import models
from django.conf import settings

# Create your models here.
class GmailAccount(models.Model):
    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE)
    email_address = models.EmailField(unique=True)
    access_token = models.TextField()
    refresh_token = models.TextField()
    token_expiry = models.DateTimeField()
    history_id = models.CharField(max_length=255, null=True, blank=True)
    last_watch_time = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)


class GmailMessage(models.Model):
    gmail_account = models.ForeignKey(GmailAccount, on_delete=models.CASCADE)
    message_id = models.CharField(max_length=128, unique=True)
    thread_id = models.CharField(max_length=128)
    subject = models.CharField(max_length=512, null=True, blank=True)
    sender = models.EmailField(null=True, blank=True)
    to = models.TextField(null=True, blank=True)
    cc = models.TextField(null=True, blank=True)
    body = models.TextField(null=True, blank=True)
    email_date = models.DateTimeField()
    labels = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.subject or 'No Subject'} from {self.sender}"
