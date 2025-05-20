from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ConversationViewSet, OrganizationConversationMetricsAPIView, UnrespondedConversationNotificationView, EmployeeConversationMetricsAPIView, ConversationStatsAPIView, MessagingCostReportView

# Create a router and register the ConversationViewSet
router = DefaultRouter()
router.register(r'', ConversationViewSet, basename='conversation')

urlpatterns = [
    path('', include(router.urls)),  # Include all router-generated URLs
    path('notification', UnrespondedConversationNotificationView.as_view()),
    path('stats', ConversationStatsAPIView.as_view()),
    path('metrics/employee', EmployeeConversationMetricsAPIView.as_view()),
    path('metrics/org', OrganizationConversationMetricsAPIView.as_view()),
    path('cost-report', MessagingCostReportView.as_view())
]
