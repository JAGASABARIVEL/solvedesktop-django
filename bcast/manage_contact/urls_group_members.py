from django.urls import path
from .views import (
    GroupMemberListCreateView, GroupMemberDetailView, BulkDeleteGroupMemberView
)

urlpatterns = [
    # Group Members
    path('', GroupMemberListCreateView.as_view(), name='group-member-list-create'),
    path('<int:pk>', GroupMemberDetailView.as_view(), name='group-member-detail'),
    path('bulk-delete', BulkDeleteGroupMemberView.as_view(), name='bulk-delete-group-members'),
]
