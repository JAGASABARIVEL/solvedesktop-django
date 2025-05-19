# views.py
import json
from django.shortcuts import get_object_or_404
from django.conf import settings
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from .models import KeyLogger
from .serializers import KeyLoggerSerializer

User = settings.AUTH_USER_MODEL

class GetUserFromUUID(APIView):
    def get(self, request, uuid):
        user = get_object_or_404(User, uuid=uuid)
        return Response({"emp_id": user.id}, status=status.HTTP_200_OK)


class KeyLoggerRecord(APIView):
    def post(self, request):
        enterprise_profile = getattr(self.request.user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        uuid = request.data.get('uuid')
        if not uuid:
            return Response({"message": "MAC not provided"}, status=status.HTTP_400_BAD_REQUEST)
        user = get_object_or_404(User, uuid=uuid)
        emp_id = user.id
        data = request.data.copy()
        data.update({
            "organization": organization,
            "emp": emp_id
        })
        # Check for existing record
        keylog = KeyLogger.objects.filter(
            organization_id=organization,
            emp_id=emp_id,
            date=data.get('date')
        ).first()
        if keylog:
            # Update existing record
            serializer = KeyLoggerSerializer(keylog, data=data, partial=True)
            action = "Updating existing record"
        else:
            # Create new record
            serializer = KeyLoggerSerializer(data=data)
            action = "Creating new record"
        if serializer.is_valid():
            serializer.save()
            return Response({"message": f"Keylogger log added: {action}"}, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        enterprise_profile = getattr(self.request.user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        emp_id = request.query_params.get('emp_id')
        date = request.query_params.get('date')

        if not emp_id or not organization:
            return Response({"message": "Emp and Org is mandatory"}, status=status.HTTP_400_BAD_REQUEST)

        # Filter records
        queryset = KeyLogger.objects.filter(organization_id=organization, emp_id=emp_id)
        if date:
            queryset = queryset.filter(date=date)

        if not queryset.exists():
            return Response({}, status=status.HTTP_200_OK)

        emp = get_object_or_404(User, id=emp_id)
        response = {}

        for record in queryset:
            app_details = json.loads(record.app_details)
            response[record.date] = {
                "app_log": app_details,
                "total_idle_time": record.idle_time
            }
        return Response({emp.name: response}, status=status.HTTP_200_OK)
