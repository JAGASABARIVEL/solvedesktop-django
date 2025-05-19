from django.urls import path
from .views import OrganizationListView, OrganizationDetailView

urlpatterns = [
    path('', OrganizationListView.as_view(), name='organization-list'),
    path('<int:pk>', OrganizationDetailView.as_view(), name='organization-detail'),
]
