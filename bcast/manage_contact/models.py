from django.db import models

# Create your models here.
from django.db import models
from django.conf import settings

class Contact(models.Model):
    PLATFORM_CHOICES = [('whatsapp', 'WhatsApp'), ('messenger', 'Messenger'), ('telegram', 'Telegram'), ('gmail', 'Gmail'), ('webchat', 'Webchat')]
    name = models.TextField()
    description = models.TextField(blank=True, null=True)
    image = models.URLField(max_length=2048, blank=True, null=True)
    image_expires_at = models.BigIntegerField(blank=True, null=True)  # milliseconds
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
    frappe_contact_id = models.CharField(blank=True, max_length=255, null=True, unique=True)
    frappe_synced = models.BooleanField(default=False, db_index=True)
    frappe_last_sync = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.name
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['phone', 'organization'], name='unique_phone_per_org')
        ]


class ContactCustomField(models.Model):
    FIELD_TYPES = [
        ('text', 'Text'),
        ('number', 'Number'),
        ('dropdown', 'Dropdown'),
        ('checkbox', 'Checkbox'),
        ('date', 'Date'),
    ]

    organization = models.ForeignKey(
        settings.ORG_MODEL, on_delete=models.CASCADE, related_name='contact_custom_fields'
    )
    name = models.CharField(max_length=255)  # e.g., "GST Number"
    key = models.SlugField(max_length=100)   # used in frontend and storage
    field_type = models.CharField(max_length=20, choices=FIELD_TYPES)
    options = models.JSONField(blank=True, null=True)  # only for dropdowns/checkboxes
    required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    def delete(self, *args, **kwargs):
        # Delete all values for this custom field
        ContactCustomFieldValue.objects.filter(custom_field=self).delete()
        super().delete(*args, **kwargs)
    class Meta:
        unique_together = ('organization', 'key')
    def __str__(self):
        return f"{self.name} ({self.organization})"


class ContactCustomFieldValue(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='custom_field_values')
    custom_field = models.ForeignKey(ContactCustomField, on_delete=models.CASCADE)
    value = models.TextField(blank=True, null=True)  # always stored as string
    class Meta:
        unique_together = ('contact', 'custom_field')
    def __str__(self):
        return f"{self.custom_field.key}: {self.value}"


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