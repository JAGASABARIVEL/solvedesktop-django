# ==========================================
# FILE: manage_crm/apps.py
# ==========================================
"""
CRM app configuration
"""

from django.apps import AppConfig


class ManageCrmConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'manage_crm'
    
    def ready(self):
        """Register signal handlers when app is ready"""
        from manage_crm.sync_handlers import register_signals
        register_signals()


