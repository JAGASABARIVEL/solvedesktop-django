# ==========================================
# FILE: manage_crm/sync_service.py
# ==========================================
"""
Synchronization service for Phase 1
"""

import logging
from typing import Tuple
from django.utils.timezone import now
from django.db.models import Q
from manage_contact.models import Contact
from manage_users.models import CustomUser, EnterpriseProfile

logger = logging.getLogger(__name__)


class Phase1SyncService:
    """
    Phase 1: Sync Contacts and Employees to Frappe CRM
    Zero bugs, production-ready
    """
    
    def __init__(self, organization, frappe_client):
        self.organization = organization
        self.frappe_client = frappe_client
        self.sync_config = organization.crm_sync_config
    
    def sync_all_contacts(self) -> Tuple[int, int, str]:
        """
        Sync all contacts for organization to Frappe
        
        Returns:
            Tuple (synced_count, failed_count, message)
        """
        if not self.sync_config.auto_sync_contacts:
            msg = "Contact sync disabled"
            logger.info(msg)
            return 0, 0, msg
        
        logger.info(f"Starting contact sync for org: {self.organization.name}")
        
        # Mark as syncing
        self.sync_config.is_syncing = True
        self.sync_config.sync_error = None
        self.sync_config.save(update_fields=['is_syncing', 'sync_error'])
        
        try:
            # Get unsync'd contacts
            contacts = Contact.objects.filter(
                organization=self.organization,
                frappe_synced=False
            ).order_by('created_at')
            
            synced = 0
            failed = 0
            
            logger.info(f"Found {contacts.count()} unsync'd contacts")
            
            for contact in contacts:
                try:
                    success, frappe_data = self.frappe_client.get_or_create_contact(
                        phone=contact.phone,
                        name=contact.name,
                        email=getattr(contact, 'email', None),
                        platform=contact.platform_name
                    )
                    
                    if success and frappe_data:
                        # Update with Frappe reference
                        contact.frappe_contact_id = frappe_data['name']
                        contact.frappe_synced = True
                        contact.frappe_last_sync = now()
                        contact.save(update_fields=[
                            'frappe_contact_id',
                            'frappe_synced',
                            'frappe_last_sync'
                        ])
                        
                        synced += 1
                        
                        # Log success
                        from manage_crm.models import CRMSyncLog
                        CRMSyncLog.objects.create(
                            organization=self.organization,
                            django_id=contact.id,
                            frappe_id=frappe_data['name'],
                            doctype='Contact',
                            status='success'
                        )
                        
                    else:
                        failed += 1
                        logger.error(
                            f"Failed to sync contact {contact.id}: "
                            f"Success={success}"
                        )
                        
                except Exception as e:
                    failed += 1
                    logger.error(
                        f"Exception syncing contact {contact.id}: {e}",
                        exc_info=True
                    )
            
            # Update sync config
            self.sync_config.last_contact_sync = now()
            self.sync_config.is_syncing = False
            self.sync_config.save(update_fields=[
                'last_contact_sync',
                'is_syncing'
            ])
            
            msg = f"Synced {synced} contacts, {failed} failed"
            logger.info(f"✅ {msg}")
            return synced, failed, msg
            
        except Exception as e:
            logger.error(f"Critical error in contact sync: {e}", exc_info=True)
            self.sync_config.is_syncing = False
            self.sync_config.sync_error = str(e)
            self.sync_config.save(update_fields=['is_syncing', 'sync_error'])
            return 0, 0, f"Error: {str(e)}"
    
    def sync_all_employees(self) -> Tuple[int, int, str]:
        """
        Sync all employees for organization to Frappe
        
        Returns:
            Tuple (synced_count, failed_count, message)
        """
        if not self.sync_config.auto_sync_employees:
            msg = "Employee sync disabled"
            logger.info(msg)
            return 0, 0, msg
        
        logger.info(f"Starting employee sync for org: {self.organization.name}")
        
        self.sync_config.is_syncing = True
        self.sync_config.sync_error = None
        self.sync_config.save(update_fields=['is_syncing', 'sync_error'])
        
        try:
            # Get org users
            enterprise_profiles = EnterpriseProfile.objects.filter(
                organization=self.organization
            ).select_related('user')
            
            synced = 0
            failed = 0
            
            logger.info(f"Found {enterprise_profiles.count()} employees")
            
            for profile in enterprise_profiles:
                user = profile.user
                
                try:
                    success, frappe_user = self.frappe_client.get_or_create_user(
                        email=user.email,
                        first_name=user.username or user.email.split('@')[0],
                        last_name=getattr(user, 'last_name', ''),
                        user_type="System Manager" if user.user_type == "owner" else "User"
                    )
                    
                    if success and frappe_user:
                        # Update with Frappe reference
                        user.frappe_user_id = frappe_user['name']
                        user.frappe_synced = True
                        user.save(update_fields=[
                            'frappe_user_id',
                            'frappe_synced'
                        ])
                        
                        synced += 1
                        
                        # Log success
                        from manage_crm.models import CRMSyncLog
                        CRMSyncLog.objects.create(
                            organization=self.organization,
                            django_id=user.id,
                            frappe_id=frappe_user['name'],
                            doctype='User',
                            status='success'
                        )
                    else:
                        failed += 1
                        logger.error(
                            f"Failed to sync user {user.id} ({user.email})"
                        )
                        
                except Exception as e:
                    failed += 1
                    logger.error(
                        f"Exception syncing user {user.id}: {e}",
                        exc_info=True
                    )
            
            # Update sync config
            self.sync_config.last_employee_sync = now()
            self.sync_config.is_syncing = False
            self.sync_config.save(update_fields=[
                'last_employee_sync',
                'is_syncing'
            ])
            
            msg = f"Synced {synced} employees, {failed} failed"
            logger.info(f"✅ {msg}")
            return synced, failed, msg
            
        except Exception as e:
            logger.error(f"Critical error in employee sync: {e}", exc_info=True)
            self.sync_config.is_syncing = False
            self.sync_config.sync_error = str(e)
            self.sync_config.save(update_fields=['is_syncing', 'sync_error'])
            return 0, 0, f"Error: {str(e)}"


# ==========================================
# FILE: manage_crm/management/commands/sync_to_frappe.py
# ==========================================
"""
Django management command for CRM sync
Usage: python manage.py sync_to_frappe --org-id=1 --contacts --employees
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from manage_organization.models import Organization
from manage_crm.frappe_client import FrappeAPIClient, FrappeConnectionError
from manage_crm.sync_service import Phase1SyncService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sync contacts and employees to Frappe CRM'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--org-id',
            type=int,
            help='Organization ID to sync'
        )
        parser.add_argument(
            '--all-orgs',
            action='store_true',
            help='Sync all organizations'
        )
        parser.add_argument(
            '--contacts',
            action='store_true',
            help='Sync contacts'
        )
        parser.add_argument(
            '--employees',
            action='store_true',
            help='Sync employees'
        )
        parser.add_argument(
            '--test-connection',
            action='store_true',
            help='Test Frappe connection only'
        )
    
    def handle(self, *args, **options):
        org_id = options.get('org_id')
        all_orgs = options.get('all_orgs')
        sync_contacts = options.get('contacts')
        sync_employees = options.get('employees')
        test_connection = options.get('test_connection')
        
        # Default to both if neither specified
        if not sync_contacts and not sync_employees and not test_connection:
            sync_contacts = True
            sync_employees = True
        
        # Get organizations to sync
        if all_orgs:
            orgs = Organization.objects.filter(frappe_enabled=True)
            self.stdout.write(f"Syncing {orgs.count()} organizations...")
        elif org_id:
            try:
                orgs = [Organization.objects.get(id=org_id)]
            except Organization.DoesNotExist:
                raise CommandError(f"Organization {org_id} not found")
        else:
            raise CommandError("Specify --org-id or --all-orgs")
        
        for org in orgs:
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"Organization: {org.name} (ID: {org.id})")
            self.stdout.write(f"{'='*60}")
            
            # Initialize Frappe client
            try:
                frappe_client = FrappeAPIClient(org)
            except FrappeConnectionError as e:
                self.stdout.write(
                    self.style.ERROR(f"❌ Frappe not configured: {e}")
                )
                continue
            
            # Test connection
            if test_connection or sync_contacts or sync_employees:
                self.stdout.write("Testing Frappe connection...")
                if frappe_client.test_connection():
                    self.stdout.write(
                        self.style.SUCCESS("✅ Connection successful")
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR("❌ Connection failed")
                    )
                    continue
            
            if test_connection:
                continue
            
            # Initialize sync service
            try:
                sync_service = Phase1SyncService(org, frappe_client)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"❌ Failed to initialize sync: {e}")
                )
                continue
            
            # Sync contacts
            if sync_contacts:
                self.stdout.write("\nSyncing contacts...")
                try:
                    synced, failed, msg = sync_service.sync_all_contacts()
                    if failed == 0:
                        self.stdout.write(
                            self.style.SUCCESS(f"✅ {msg}")
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(f"⚠️  {msg}")
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"❌ Contact sync failed: {e}")
                    )
            
            # Sync employees
            if sync_employees:
                self.stdout.write("\nSyncing employees...")
                try:
                    synced, failed, msg = sync_service.sync_all_employees()
                    if failed == 0:
                        self.stdout.write(
                            self.style.SUCCESS(f"✅ {msg}")
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(f"⚠️  {msg}")
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"❌ Employee sync failed: {e}")
                    )
        
        self.stdout.write(
            self.style.SUCCESS("\n✅ Sync complete!")
        )