# ==========================================
# FILE: manage_crm/urls.py
# ==========================================
"""
CRM API URLs
"""

from django.urls import path
from manage_crm.views import (
    FrappeSetupView,
    FrappeTestConnectionView,
    SyncContactsView,
    SyncEmployeesView,
    SyncLogsView
)

urlpatterns = [
    path('setup/', FrappeSetupView.as_view(), name='frappe-setup'),
    path('test-connection/', FrappeTestConnectionView.as_view(), name='test-connection'),
    path('sync/contacts/', SyncContactsView.as_view(), name='sync-contacts'),
    path('sync/employees/', SyncEmployeesView.as_view(), name='sync-employees'),
    path('sync/logs/', SyncLogsView.as_view(), name='sync-logs'),
]