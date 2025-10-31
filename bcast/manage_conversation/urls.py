from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ConversationViewSet, ChatWindowConversationViewSet, OrganizationConversationMetricsAPIView, UnrespondedConversationNotificationView, EmployeeConversationMetricsAPIView, ConversationStatsAPIView, MessagingCostReportView

# Create a router and register the ConversationViewSet
nonchat_router = DefaultRouter()
nonchat_router.register(r'', ConversationViewSet, basename='conversation')

router = DefaultRouter()
router.register(r'', ChatWindowConversationViewSet, basename='chatconversation')

urlpatterns = [
    path('conversation/', include(nonchat_router.urls)),  # Include all router-generated URLs for non chat
    path('', include(router.urls)),  # Include all router-generated URLs for chat
    path('notification', UnrespondedConversationNotificationView.as_view()),
    path('stats', ConversationStatsAPIView.as_view()),
    path('metrics/employee', EmployeeConversationMetricsAPIView.as_view()),
    path('metrics/org', OrganizationConversationMetricsAPIView.as_view()),
    path('cost-report', MessagingCostReportView.as_view())
]

