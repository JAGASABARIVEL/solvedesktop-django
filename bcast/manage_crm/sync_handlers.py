# ==========================================
# FILE: manage_crm/sync_handlers.py
# ==========================================
"""
Sync handlers - triggered automatically on CRUD operations
Handles all async syncing to Frappe CRM
"""

import logging
from typing import Optional, Dict
from django.db import transaction
from celery import shared_task
from manage_crm.frappe_client import FrappeAPIClient, FrappeConnectionError
from manage_crm.models import CRMSyncLog

logger = logging.getLogger(__name__)


# =====================
# CONTACT SYNC HANDLERS
# =====================

@shared_task(bind=True, max_retries=3)
def sync_contact_to_crm(self, contact_id: int):
    """
    Async task to sync contact to Frappe CRM
    Automatically called when contact is created/updated
    
    Args:
        contact_id: Django Contact ID
    """
    from manage_contact.models import Contact
    
    try:
        contact = Contact.objects.get(id=contact_id)
    except Contact.DoesNotExist:
        logger.warning(f"Contact {contact_id} not found")
        return
    
    organization = contact.organization
    
    # Skip if CRM not enabled
    if not organization.frappe_enabled:
        logger.debug(f"CRM not enabled for org {organization.id}")
        return
    
    try:
        frappe_client = FrappeAPIClient(organization)
    except FrappeConnectionError as e:
        logger.error(f"CRM connection failed: {e}")
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
    
    try:
        logger.info(f"Syncing contact {contact_id} to CRM")
        
        # Check if already synced
        if contact.frappe_contact_id:
            # Update existing
            logger.debug(f"Updating existing CRM contact: {contact.frappe_contact_id}")
            # For now, contact updates are read-only from Frappe side
            # In Phase 2, implement bi-directional updates
            return
        
        # Create new contact
        success, frappe_data = frappe_client.get_or_create_contact(
            phone=contact.phone,
            name=contact.name,
            email=getattr(contact, 'email', None),
            platform=contact.platform_name
        )
        
        if success and frappe_data:
            # Update local contact with CRM reference
            contact.frappe_contact_id = frappe_data['name']
            contact.frappe_synced = True
            contact.frappe_last_sync = __import__('django.utils.timezone', fromlist=['now']).now()
            contact.save(update_fields=[
                'frappe_contact_id',
                'frappe_synced',
                'frappe_last_sync'
            ])
            
            # Log success
            CRMSyncLog.objects.create(
                organization=organization,
                django_id=contact.id,
                frappe_id=frappe_data['name'],
                doctype='Contact',
                status='success',
                details=f"Contact synced: {contact.name}"
            )
            
            logger.info(f"✅ Contact {contact_id} synced as {frappe_data['name']}")
        else:
            logger.error(f"Failed to sync contact {contact_id}")
            CRMSyncLog.objects.create(
                organization=organization,
                django_id=contact.id,
                frappe_id='',
                doctype='Contact',
                status='failed',
                details=f"Failed to create contact in CRM"
            )
    
    except FrappeConnectionError as e:
        logger.error(f"CRM connection error: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
    except Exception as e:
        logger.error(f"Unexpected error syncing contact {contact_id}: {e}", exc_info=True)
        CRMSyncLog.objects.create(
            organization=organization,
            django_id=contact_id,
            frappe_id='',
            doctype='Contact',
            status='failed',
            details=f"Error: {str(e)}"
        )


@shared_task(bind=True, max_retries=3)
def delete_contact_from_crm(self, frappe_contact_id: str, organization_id: int):
    """
    Async task to delete contact from Frappe CRM
    Automatically called when contact is deleted
    
    Args:
        frappe_contact_id: Frappe Contact name
        organization_id: Organization ID
    """
    from manage_organization.models import Organization
    
    try:
        organization = Organization.objects.get(id=organization_id)
    except Organization.DoesNotExist:
        logger.warning(f"Organization {organization_id} not found")
        return
    
    if not organization.frappe_enabled:
        return
    
    try:
        frappe_client = FrappeAPIClient(organization)
        
        logger.info(f"Deleting contact {frappe_contact_id} from CRM")
        
        # Soft delete in Frappe (set disabled=1)
        response = frappe_client._make_request(
            "PUT",
            f"/Contact/{frappe_contact_id}",
            data={"disabled": 1}
        )
        
        if response.success:
            logger.info(f"✅ Contact {frappe_contact_id} deleted from CRM")
            CRMSyncLog.objects.create(
                organization=organization,
                django_id=0,  # No local ID
                frappe_id=frappe_contact_id,
                doctype='Contact',
                status='success',
                details='Contact soft-deleted from CRM'
            )
        else:
            logger.error(f"Failed to delete contact from CRM: {response.error}")
            raise Exception(f"Delete failed: {response.error}")
    
    except FrappeConnectionError as e:
        logger.error(f"CRM connection error: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
    except Exception as e:
        logger.error(f"Error deleting contact from CRM: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


# =====================
# EMPLOYEE/USER SYNC HANDLERS
# =====================

@shared_task(bind=True, max_retries=3)
def sync_user_to_crm(self, user_id: int):
    """
    Async task to sync user to Frappe CRM
    Automatically called when user is created/updated
    
    Args:
        user_id: Django CustomUser ID
    """
    from manage_users.models import CustomUser, EnterpriseProfile
    
    try:
        user = CustomUser.objects.get(id=user_id)
    except CustomUser.DoesNotExist:
        logger.warning(f"User {user_id} not found")
        return
    
    # Get user's organization
    try:
        enterprise_profile = user.enterprise_profile
        organization = enterprise_profile.organization
    except EnterpriseProfile.DoesNotExist:
        logger.debug(f"User {user_id} not part of any organization")
        return
    
    # Skip if CRM not enabled
    if not organization.frappe_enabled:
        logger.debug(f"CRM not enabled for org {organization.id}")
        return
    
    try:
        frappe_client = FrappeAPIClient(organization)
    except FrappeConnectionError as e:
        logger.error(f"CRM connection failed: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
    
    try:
        logger.info(f"Syncing user {user_id} to CRM")
        
        # Check if already synced
        if user.frappe_synced:
            logger.debug(f"User {user_id} already synced")
            # In Phase 2, implement updates
            return
        
        # Determine user type
        frappe_user_type = "System Manager" if user.user_type == "owner" else "User"
        
        # Create user
        success, frappe_user = frappe_client.get_or_create_user(
            email=user.email,
            first_name=user.username or user.email.split('@')[0],
            last_name=getattr(user, 'last_name', ''),
            user_type=frappe_user_type
        )
        
        if success and frappe_user:
            # Update local user with CRM reference
            user.frappe_user_id = frappe_user['name']
            user.frappe_synced = True
            user.save(update_fields=['frappe_user_id', 'frappe_synced'])
            
            # Log success
            CRMSyncLog.objects.create(
                organization=organization,
                django_id=user.id,
                frappe_id=frappe_user['name'],
                doctype='User',
                status='success',
                details=f"User synced: {user.email}"
            )
            
            logger.info(f"✅ User {user_id} synced as {frappe_user['name']}")
        else:
            logger.error(f"Failed to sync user {user_id}")
            CRMSyncLog.objects.create(
                organization=organization,
                django_id=user.id,
                frappe_id='',
                doctype='User',
                status='failed',
                details='Failed to create user in CRM'
            )
    
    except FrappeConnectionError as e:
        logger.error(f"CRM connection error: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
    except Exception as e:
        logger.error(f"Unexpected error syncing user {user_id}: {e}", exc_info=True)
        try:
            organization = user.enterprise_profile.organization
            CRMSyncLog.objects.create(
                organization=organization,
                django_id=user_id,
                frappe_id='',
                doctype='User',
                status='failed',
                details=f"Error: {str(e)}"
            )
        except:
            pass


# =====================
# SIGNAL HANDLERS (Connect to Django signals)
# =====================

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from manage_contact.models import Contact
from manage_users.models import CustomUser


@receiver(post_save, sender=Contact)
def handle_contact_saved(sender, instance, created, **kwargs):
    """
    Signal handler - triggered when Contact is saved
    Automatically enqueue sync task
    """
    # Don't sync if already has CRM ID (avoid redundant syncs)
    if instance.frappe_contact_id:
        return
    
    # Skip if organization doesn't have CRM enabled
    if not instance.organization.frappe_enabled:
        return
    
    logger.info(f"Contact {instance.id} saved, enqueueing CRM sync")
    
    # Enqueue async task (non-blocking)
    sync_contact_to_crm.delay(instance.id)


@receiver(post_delete, sender=Contact)
def handle_contact_deleted(sender, instance, **kwargs):
    """
    Signal handler - triggered when Contact is deleted
    Soft-delete from CRM
    """
    if not instance.frappe_contact_id:
        return
    
    if not instance.organization.frappe_enabled:
        return
    
    logger.info(f"Contact {instance.id} deleted, enqueueing CRM deletion")
    
    # Enqueue async task
    delete_contact_from_crm.delay(
        instance.frappe_contact_id,
        instance.organization.id
    )


@receiver(post_save, sender=CustomUser)
def handle_user_saved(sender, instance, created, **kwargs):
    """
    Signal handler - triggered when User is saved
    Automatically enqueue sync task
    """
    # Don't sync superusers
    if instance.is_superuser:
        return
    
    # Don't sync if already synced
    if instance.frappe_synced:
        return
    
    # Check if user is part of organization
    try:
        enterprise_profile = instance.enterprise_profile
        if not enterprise_profile.organization.frappe_enabled:
            return
    except:
        return
    
    logger.info(f"User {instance.id} saved, enqueueing CRM sync")
    
    # Enqueue async task
    sync_user_to_crm.delay(instance.id)


def register_signals():
    """
    Register all signal handlers
    Call this in apps.py ready() method
    """
    logger.info("✅ CRM sync signal handlers registered")
