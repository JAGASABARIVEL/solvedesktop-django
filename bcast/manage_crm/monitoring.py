# ==========================================
# FILE: manage_crm/monitoring.py
# ==========================================
"""
Monitor sync queue and failed tasks
"""

import logging
from celery.app.control import Inspect
from manage_crm.sync_handlers import sync_contact_to_crm, sync_user_to_crm

logger = logging.getLogger(__name__)


class SyncQueueMonitor:
    """Monitor Celery task queue"""
    
    @staticmethod
    def get_pending_syncs() -> Dict:
        """Get pending sync tasks"""
        try:
            from django_celery_results.models import TaskResult
            
            pending = TaskResult.objects.filter(
                status='PENDING',
                task__in=[
                    'manage_crm.sync_handlers.sync_contact_to_crm',
                    'manage_crm.sync_handlers.sync_user_to_crm'
                ]
            ).count()
            
            return {
                "pending_tasks": pending,
                "status": "healthy" if pending < 100 else "warning"
            }
        except Exception as e:
            logger.error(f"Error checking queue: {e}")
            return {"error": str(e)}
    
    @staticmethod
    def get_failed_syncs() -> Dict:
        """Get failed sync tasks"""
        try:
            from django_celery_results.models import TaskResult
            
            failed = TaskResult.objects.filter(
                status='FAILURE',
                task__in=[
                    'manage_crm.sync_handlers.sync_contact_to_crm',
                    'manage_crm.sync_handlers.sync_user_to_crm'
                ]
            ).values('task').annotate(count=__import__('django.db.models', fromlist=['Count']).Count('id'))
            
            return {
                "failed_tasks": list(failed),
                "total_failed": sum(f['count'] for f in failed)
            }
        except Exception as e:
            logger.error(f"Error checking failures: {e}")
            return {"error": str(e)}


