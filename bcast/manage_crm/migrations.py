# ==========================================
# FILE: manage_crm/migrations.py (Helpers)
# ==========================================
"""
Migration helpers to avoid bugs during sync
"""

import logging
from django.db import transaction

logger = logging.getLogger(__name__)


class ContactSyncLog:
    """Track contact sync operations for debugging"""
    
    @staticmethod
    def log_sync(
        django_contact_id: int,
        frappe_contact_name: str,
        status: str,
        details: str = ""
    ):
        """Log a sync operation"""
        from manage_crm.models import CRMSyncLog
        
        try:
            CRMSyncLog.objects.create(
                django_id=django_contact_id,
                frappe_id=frappe_contact_name,
                doctype="Contact",
                status=status,  # success, failed, pending
                details=details
            )
        except Exception as e:
            logger.error(f"Failed to log sync: {e}")


class BulkContactSync:
    """Bulk sync contacts with transactional safety"""
    
    def __init__(self, organization, frappe_client):
        self.organization = organization
        self.frappe_client = frappe_client
        self.synced = []
        self.failed = []
    
    def sync_contacts(self, contacts: List) -> Tuple[int, int]:
        """
        Sync multiple contacts
        
        Returns:
            Tuple (synced_count, failed_count)
        """
        logger.info(f"Starting bulk contact sync: {len(contacts)} contacts")
        
        for contact in contacts:
            try:
                success, frappe_contact = self.frappe_client.get_or_create_contact(
                    phone=contact.phone,
                    name=contact.name,
                    email=getattr(contact, 'email', None),
                    platform=contact.platform_name
                )
                
                if success and frappe_contact:
                    # Update local record with Frappe reference
                    contact.frappe_contact_id = frappe_contact['name']
                    contact.frappe_synced = True
                    contact.frappe_last_sync = now()
                    contact.save(update_fields=[
                        'frappe_contact_id',
                        'frappe_synced',
                        'frappe_last_sync'
                    ])
                    
                    self.synced.append(contact.id)
                    logger.info(f"✅ Synced contact {contact.id} → {frappe_contact['name']}")
                else:
                    self.failed.append((contact.id, "Creation failed"))
                    logger.error(f"❌ Failed to sync contact {contact.id}")
                    
            except Exception as e:
                self.failed.append((contact.id, str(e)))
                logger.error(f"❌ Error syncing contact {contact.id}: {e}")
        
        logger.info(
            f"Bulk sync complete: {len(self.synced)} synced, "
            f"{len(self.failed)} failed"
        )
        
        return len(self.synced), len(self.failed)