# urls.py
from django.urls import path
from .views import (
    ScheduledMessageListCreateAPIView,
    ScheduledMessageRetrieveUpdateDeleteAPIView,
    ScheduledMessageBulkDeleteAPIView,
    ScheduleMessageHistoryView
)

urlpatterns = [
    path('', ScheduledMessageListCreateAPIView.as_view(), name='scheduled-message-list-create'),
    path('<int:pk>', ScheduledMessageRetrieveUpdateDeleteAPIView.as_view(), name='scheduled-message-detail'),
    path('bulk-delete', ScheduledMessageBulkDeleteAPIView.as_view(), name='scheduled-message-bulk-delete'),
    path('history', ScheduleMessageHistoryView.as_view(), name='schedule-history'),
]
