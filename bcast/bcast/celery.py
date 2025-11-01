# bcast/celery.py

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bcast.settings')

app = Celery('bcast')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()