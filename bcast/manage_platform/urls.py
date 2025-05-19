from django.urls import path
from .views import PlatformListCreateView, PlatformRetrieveUpdateDeleteView, PlatformTemplateAPIView

urlpatterns = [
    path('', PlatformListCreateView.as_view(), name='platform-list-create'),
    path('<int:pk>', PlatformRetrieveUpdateDeleteView.as_view(), name='platform-detail'),
    path('<int:platform_id>/templates', PlatformTemplateAPIView.as_view(), name='platform-templates'),
]
