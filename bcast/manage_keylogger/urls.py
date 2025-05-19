# urls.py
from django.urls import path
from .views import GetUserFromUUID, KeyLoggerRecord

urlpatterns = [
    path('<uuid:uuid>', GetUserFromUUID.as_view(), name='get_user_from_uuid'),
    path('', KeyLoggerRecord.as_view(), name='keylogger_record'),
]

