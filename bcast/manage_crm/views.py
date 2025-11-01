# ==========================================
# FILE: manage_crm/views.py
# ==========================================
"""
API views for CRM operations
"""

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from manage_users.permissions import EnterpriserUsers
from manage_crm.frappe_client import FrappeAPIClient, FrappeConnectionError
from manage_crm.sync_service import Phase1SyncService
from manage_crm.models import CRMSyncConfig, CRMSyncLog
import logging

logger = logging.getLogger(__name__)


class FrappeSetupView(APIView):
    """Setup Frappe CRM for organization"""
    permission_classes = [EnterpriserUsers]
    
    def post(self, request):
        """Configure Frappe CRM"""
        organization = request.user.enterprise_profile.organization
        
        frappe_site = request.data.get('frappe_site_name')
        api_token = request.data.get('frappe_api_token')
        
        if not frappe_site or not api_token:
            return Response(
                {"error": "frappe_site_name and frappe_api_token required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate connection
        try:
            test_org = type('', (), {
                'frappe_site_name': frappe_site,
                'frappe_api_token': api_token,
                'frappe_enabled': True,
                'id': organization.id
            })()
            
            test_client = FrappeAPIClient(test_org)
            if not test_client.test_connection():
                return Response(
                    {"error": "Failed to connect to Frappe CRM"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except FrappeConnectionError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Save configuration
        organization.frappe_site_name = frappe_site
        organization.frappe_api_token = api_token
        organization.frappe_enabled = True
        organization.save(update_fields=[
            'frappe_site_name',
            'frappe_api_token',
            'frappe_enabled'
        ])
        
        # Create sync config if not exists
        CRMSyncConfig.objects.get_or_create(
            organization=organization,
            defaults={
                'auto_sync_contacts': True,
                'auto_sync_employees': True
            }
        )
        
        return Response(
            {"message": "Frappe CRM configured successfully"},
            status=status.HTTP_200_OK
        )


class FrappeTestConnectionView(APIView):
    """Test Frappe CRM connection"""
    permission_classes = [EnterpriserUsers]
    
    def get(self, request):
        """Test connection"""
        organization = request.user.enterprise_profile.organization
        
        if not organization.frappe_enabled:
            return Response(
                {"error": "Frappe CRM not configured"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            frappe_client = FrappeAPIClient(organization)
            if frappe_client.test_connection():
                return Response(
                    {
                        "status": "connected",
                        "site": organization.frappe_site_name
                    },
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {"status": "connection_failed"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except FrappeConnectionError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class SyncContactsView(APIView):
    """Manually trigger contact sync"""
    permission_classes = [EnterpriserUsers]
    
    def post(self, request):
        """Sync contacts"""
        organization = request.user.enterprise_profile.organization
        
        if not organization.frappe_enabled:
            return Response(
                {"error": "Frappe CRM not configured"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        sync_config = organization.crm_sync_config
        if sync_config.is_syncing:
            return Response(
                {"error": "Sync already in progress"},
                status=status.HTTP_409_CONFLICT
            )
        
        try:
            frappe_client = FrappeAPIClient(organization)
            sync_service = Phase1SyncService(organization, frappe_client)
            
            synced, failed, msg = sync_service.sync_all_contacts()
            
            return Response(
                {
                    "message": msg,
                    "synced": synced,
                    "failed": failed
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SyncEmployeesView(APIView):
    """Manually trigger employee sync"""
    permission_classes = [EnterpriserUsers]
    
    def post(self, request):
        """Sync employees"""
        organization = request.user.enterprise_profile.organization
        
        if not organization.frappe_enabled:
            return Response(
                {"error": "Frappe CRM not configured"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        sync_config = organization.crm_sync_config
        if sync_config.is_syncing:
            return Response(
                {"error": "Sync already in progress"},
                status=status.HTTP_409_CONFLICT
            )
        
        try:
            frappe_client = FrappeAPIClient(organization)
            sync_service = Phase1SyncService(organization, frappe_client)
            
            synced, failed, msg = sync_service.sync_all_employees()
            
            return Response(
                {
                    "message": msg,
                    "synced": synced,
                    "failed": failed
                },
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SyncLogsView(generics.ListAPIView):
    """View CRM sync logs"""
    permission_classes = [EnterpriserUsers]
    
    def get_queryset(self):
        organization = self.request.user.enterprise_profile.organization
        return CRMSyncLog.objects.filter(
            organization=organization
        ).order_by('-synced_at')[:100]
    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        
        logs = [{
            'id': log.id,
            'doctype': log.doctype,
            'django_id': log.django_id,
            'frappe_id': log.frappe_id,
            'status': log.status,
            'details': log.details,
            'synced_at': log.synced_at.isoformat()
        } for log in queryset]
        
        return Response(logs)

# ==========================================
# FILE: manage_crm/views.py (ADD THIS ENDPOINT)
# ==========================================
"""
Monitoring endpoint for sync queue
"""

class SyncQueueStatusView(APIView):
    """Check sync queue status"""
    permission_classes = [EnterpriserUsers]
    
    def get(self, request):
        """Get sync queue and failure status"""
        from manage_crm.monitoring import SyncQueueMonitor
        
        queue_status = SyncQueueMonitor.get_pending_syncs()
        failed_status = SyncQueueMonitor.get_failed_syncs()
        
        return Response({
            "queue": queue_status,
            "failed": failed_status
        })