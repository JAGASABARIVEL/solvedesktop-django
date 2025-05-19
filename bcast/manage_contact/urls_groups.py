from django.urls import path
from .views import (
    ContactGroupListCreateView, ContactGroupDetailView, BulkDeleteGroupView,
)

urlpatterns = [
    # Contact Groups
    path('', ContactGroupListCreateView.as_view(), name='group-list-create'),
    path('<int:pk>', ContactGroupDetailView.as_view(), name='group-detail'),
    path('bulk-delete', BulkDeleteGroupView.as_view(), name='bulk-delete-groups'),
]
