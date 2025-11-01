# ==========================================
# FILE: manage_crm/models.py
# ==========================================
"""
CRM sync tracking models
"""

from django.db import models
from django.conf import settings


class CRMSyncLog(models.Model):
    """Log all CRM sync operations for debugging"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('partial', 'Partial')
    ]
    
    DOCTYPE_CHOICES = [
        ('Contact', 'Contact'),
        ('User', 'User'),
        ('Lead', 'Lead'),
        ('Issue', 'Issue'),
    ]
    
    organization = models.ForeignKey(
        settings.ORG_MODEL,
        on_delete=models.CASCADE,
        related_name='crm_sync_logs'
    )
    
    django_id = models.IntegerField()  # Local Django record ID
    frappe_id = models.CharField(max_length=255)  # Frappe docname
    doctype = models.CharField(max_length=50, choices=DOCTYPE_CHOICES)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    details = models.TextField(blank=True, null=True)
    
    synced_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-synced_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['django_id', 'doctype']),
            models.Index(fields=['frappe_id']),
        ]
    
    def __str__(self):
        return f"{self.doctype}({self.django_id}) → {self.frappe_id} [{self.status}]"


class CRMSyncConfig(models.Model):
    """Configuration for CRM sync per organization"""
    
    organization = models.OneToOneField(
        settings.ORG_MODEL,
        on_delete=models.CASCADE,
        related_name='crm_sync_config'
    )
    
    # Sync settings
    auto_sync_contacts = models.BooleanField(default=True)
    auto_sync_employees = models.BooleanField(default=True)
    auto_sync_conversations = models.BooleanField(default=False)
    
    # Status
    last_contact_sync = models.DateTimeField(null=True, blank=True)
    last_employee_sync = models.DateTimeField(null=True, blank=True)
    
    is_syncing = models.BooleanField(default=False)
    sync_error = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"CRM Sync Config - {self.organization.name}"