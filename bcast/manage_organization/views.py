from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from .models import Organization
from .serializers import OrganizationSerializer
from manage_users.permissions import EnterpriserUsers

# Fetch all organizations
@method_decorator(require_http_methods(["GET"]), name='dispatch')
class OrganizationListView(generics.ListAPIView):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    permission_classes = [EnterpriserUsers]

# Fetch organization by ID
@method_decorator(require_http_methods(["GET"]), name='dispatch')
class OrganizationDetailView(generics.RetrieveAPIView):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    permission_classes = [EnterpriserUsers]
