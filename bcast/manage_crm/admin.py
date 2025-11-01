# ==========================================
# FILE: manage_crm/admin.py
# ==========================================
"""
Django admin for CRM models
"""

from django.contrib import admin
from manage_crm.models import CRMSyncLog, CRMSyncConfig


@admin.register(CRMSyncConfig)
class CRMSyncConfigAdmin(admin.ModelAdmin):
    list_display = (
        'organization',
        'auto_sync_contacts',
        'auto_sync_employees',
        'is_syncing',
        'last_contact_sync',
        'last_employee_sync'
    )
    list_filter = ('auto_sync_contacts', 'auto_sync_employees', 'is_syncing')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Organization', {
            'fields': ('organization',)
        }),
        ('Sync Settings', {
            'fields': (
                'auto_sync_contacts',
                'auto_sync_employees',
                'auto_sync_conversations'
            )
        }),
        ('Status', {
            'fields': (
                'is_syncing',
                'sync_error',
                'last_contact_sync',
                'last_employee_sync'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CRMSyncLog)
class CRMSyncLogAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'doctype',
        'django_id',
        'frappe_id',
        'status',
        'synced_at'
    )
    list_filter = ('status', 'doctype', 'synced_at')
    search_fields = ('django_id', 'frappe_id', 'doctype')
    readonly_fields = ('synced_at',)
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False