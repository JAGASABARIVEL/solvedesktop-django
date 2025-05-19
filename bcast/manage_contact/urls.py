from django.urls import path
from .views import (
    ContactListCreateView, ContactDetailView, BulkDeleteContactView, ContactImportView
)

urlpatterns = [
    # Contacts
    path('', ContactListCreateView.as_view(), name='contact-list-create'),
    path('<int:pk>', ContactDetailView.as_view(), name='contact-detail'),
    path('bulk-delete', BulkDeleteContactView.as_view(), name='bulk-delete-contacts'),
    path('import', ContactImportView.as_view(), name='contact-import'),
]
