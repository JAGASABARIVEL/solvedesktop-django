from django.urls import path
from .views import (
    ContactCustomFieldListCreateView, ContactCustomFieldRetrieveUpdateDestroyView, ContactListCreateView, ContactDetailView, BulkDeleteContactView, ContactImportView
)

urlpatterns = [
    # Contacts
    path('custom-fields', ContactCustomFieldListCreateView.as_view(), name='contact_custom_fields'),
    path('custom-fields/<int:pk>', ContactCustomFieldRetrieveUpdateDestroyView.as_view(), name='contact-custom-field-detail'),
    path('', ContactListCreateView.as_view(), name='contact-list-create'),
    path('<int:pk>', ContactDetailView.as_view(), name='contact-detail'),
    path('bulk-delete', BulkDeleteContactView.as_view(), name='bulk-delete-contacts'),
    path('import', ContactImportView.as_view(), name='contact-import'),
]
