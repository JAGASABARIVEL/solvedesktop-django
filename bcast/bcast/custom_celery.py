import os
from celery import Celery

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bcast.settings')

celery_app = Celery('bcast')

# Load task modules from all registered Django app configs.
celery_app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks across all apps
celery_app.autodiscover_tasks()
