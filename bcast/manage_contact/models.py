from django.db import models

# Create your models here.
from django.db import models
from django.conf import settings

class Contact(models.Model):
    PLATFORM_CHOICES = [
        ('whatsapp', 'WhatsApp'),
        ('telegram', 'Telegram'),
        ('gmail', 'Gmail'),
        ('webchat', 'Webchat')
    ]
    name = models.TextField()
    description = models.TextField(blank=True, null=True)
    image = models.URLField(max_length=2048, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    category = models.TextField(blank=True, null=True)
    phone = models.TextField()
    platform_name = models.TextField(choices=PLATFORM_CHOICES, default='whatsapp')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contacts'
    )
    organization = models.ForeignKey(
        settings.ORG_MODEL, on_delete=models.CASCADE, related_name='contacts'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['phone', 'organization'], name='unique_phone_per_org')
        ]


class ContactGroup(models.Model):
    name = models.TextField()
    description = models.TextField(blank=True, null=True)
    category = models.TextField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contact_groups', null=True, blank=True
    )
    organization = models.ForeignKey(
        settings.ORG_MODEL, on_delete=models.CASCADE, related_name='contact_groups'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['name', 'organization'], name='unique_group_name_per_org')
        ]


class GroupMember(models.Model):
    group = models.ForeignKey(
        ContactGroup, on_delete=models.CASCADE, related_name='members'
    )
    contact = models.ForeignKey(
        Contact, on_delete=models.CASCADE, related_name='groups'
    )
    organization = models.ForeignKey(
        settings.ORG_MODEL, on_delete=models.CASCADE, related_name='contact_member'
    )
    class Meta:
        unique_together = ('group', 'contact')

    def __str__(self):
        return f"{self.contact.name} in {self.group.name}"