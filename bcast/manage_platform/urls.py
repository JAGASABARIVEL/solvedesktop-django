from django.urls import path
from .views import BulkBlockContactView, PlatformBlockedContactView, PlatformNotificationView, PlatformListCreateView, PlatformRetrieveUpdateDeleteView, PlatformTemplateAPIView, GmailOAuthCallback

urlpatterns = [
    path('', PlatformListCreateView.as_view(), name='platform-list-create'),
    path('<int:pk>', PlatformRetrieveUpdateDeleteView.as_view(), name='platform-detail'),
    path('<int:platform_id>/templates', PlatformTemplateAPIView.as_view(), name='platform-templates'),
    path('gmail/oauth/callback', GmailOAuthCallback.as_view()),
    path('notification', PlatformNotificationView.as_view()),
    path('<int:platform_id>/blocked_contacts', PlatformBlockedContactView.as_view(), name='platform-blocked-contacts'),
    path('blocked_contacts/bulk/', BulkBlockContactView.as_view(), name='block-contact-bulk'),
]

