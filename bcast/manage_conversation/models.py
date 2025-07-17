from django.db import models
from django.conf import settings


class Conversation(models.Model):
    assigned_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_conversations')
    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE, related_name='conversations')
    platform = models.ForeignKey(settings.PLATFORM_MODEL, on_delete=models.CASCADE, related_name='conversations')
    contact = models.ForeignKey(settings.CONTACT_MODEL, on_delete=models.CASCADE, related_name='conversations')

    OPEN_BY_CHOICES = [
        ('customer', 'Customer'),
        ('agent', 'Agent')
    ]
    open_by = models.TextField(choices=OPEN_BY_CHOICES, default='customer')

    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='closed_conversations')
    closed_reason = models.TextField(blank=True, null=True)

    STATUS_CHOICES = [
        ('new', 'New'),
        ('active', 'Active'),
        ('closed', 'Closed')
    ]
    status = models.TextField(choices=STATUS_CHOICES, default='new')
    subject = models.TextField(null=True, blank=True)
    thread_id = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Conversation with {self.contact}" 


class IncomingMessage(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='incoming_messages')
    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE, related_name='incoming_messages')
    platform = models.ForeignKey(settings.PLATFORM_MODEL, on_delete=models.CASCADE, related_name='incoming_messages')
    contact = models.ForeignKey(settings.CONTACT_MODEL, on_delete=models.CASCADE, related_name='incoming_messages')

    message_type = models.TextField(default="TEXT")
    message_body = models.TextField()
    content_blocks = models.JSONField(null=True, blank=True)
    messageid = models.TextField(null=True, blank=True)
    received_time = models.DateTimeField(auto_now_add=True)

    STATUS_CHOICES = [
        ('unread', 'Unread'),
        ('read', 'Read'),
        ('responded', 'Responded')
    ]
    status = models.TextField(choices=STATUS_CHOICES, default='unread')

    status_details = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def to_dict(self):
        return {
            'id': self.contact_id,
            'conversation_id': self.conversation_id,
            'received_time': self.received_time.isoformat() if self.received_time else None,
            'message_body': self.message_body,
            'image_urls': self.image_urls,
            'status': self.status,
            'status_details': self.status_details,
            'type': 'customer'
        }


class UserMessage(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='user_messages')
    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE, related_name='user_messages')
    platform = models.ForeignKey(settings.PLATFORM_MODEL, on_delete=models.CASCADE, related_name='user_messages')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_messages')

    message_type = models.TextField(default="text")
    message_body = models.TextField()
    sent_time = models.DateTimeField(auto_now_add=True)

    status = models.TextField(blank=True, null=True)
    status_details = models.TextField(blank=True, null=True)
    messageid = models.TextField(blank=True, null=True)
    template = models.TextField(blank=True, null=True)

