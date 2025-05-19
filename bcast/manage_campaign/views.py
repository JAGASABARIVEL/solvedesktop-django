# views.py
import os
import uuid
import json
import pyexcel
from datetime import datetime
from django.conf import settings
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from manage_users.permissions import EnterpriserUsers
from .models import ScheduledMessage, PlatformLog
from .serializers import ScheduledMessageSerializer, BulkDeleteSerializer, PlatformLogHistorySerializer


def generate_unique_filename(original_filename):
    file_extension = os.path.splitext(original_filename)[1]
    unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}{file_extension}"
    return os.path.join("uploaded_files", unique_name)

def save_excel_locally(file, original_filename):
    unique_filename = generate_unique_filename(original_filename)
    file_path = default_storage.save(unique_filename, file)
    return file_path

def process_excel_from_upload(file_path):
    sheet = pyexcel.get_sheet(file_name=default_storage.path(file_path))
    data = []
    headers = sheet.row[0]  # First row as headers
    for row in sheet.row[1:]:
        data.append(dict(zip(headers, row)))
    return data

def dump_for_excel_datasource(datasource, files):
    excel_filenames = []
    for key, source in datasource.items():
        if source['type'] == 'excel' and source['file_upload'] in files:
            file = files[source['file_upload']]
            unique_filename = save_excel_locally(file, file.name)
            source['file_path'] = unique_filename
            excel_filenames.append(unique_filename)
            source['data'] = process_excel_from_upload(unique_filename)
    return excel_filenames

class ScheduledMessageListCreateAPIView(APIView):
    permission_classes = [EnterpriserUsers]
    def get(self, request):
        enterprise_profile = getattr(self.request.user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        scheduled_messages = ScheduledMessage.objects.filter(organization_id=organization).all()
        serializer = ScheduledMessageSerializer(scheduled_messages, many=True)
        return Response(serializer.data)

    def post(self, request):
        try:
            import time
            start_time = time.time()
            datasource = json.loads(request.data.get('datasource', '{}'))
            excel_filenames = dump_for_excel_datasource(datasource, request.FILES)
            mutable_data = request.data.copy()
            mutable_data['datasource'] = json.dumps(datasource)
            mutable_data['excel_filename'] = ",".join(excel_filenames)
            enterprise_profile = getattr(self.request.user, "enterprise_profile", None)
            organization = getattr(enterprise_profile, "organization", None)
            mutable_data['organization'] = organization.id
            mutable_data['user'] = self.request.user.id
            parsing_time = time.time() - start_time
            serializer = ScheduledMessageSerializer(data=mutable_data)
            serializer_time = time.time() - parsing_time
            
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


def delete_files(filenames):
    for filename in filenames:
        file_path = os.path.join(filename)
        if os.path.isfile(file_path):
            os.remove(file_path)

class ScheduledMessageRetrieveUpdateDeleteAPIView(APIView):
    permission_classes = [EnterpriserUsers]
    def get_object(self, pk):
        return get_object_or_404(ScheduledMessage, pk=pk)

    def get(self, request, pk):
        scheduled_message = self.get_object(pk)
        serializer = ScheduledMessageSerializer(scheduled_message)
        return Response(serializer.data)

    def put(self, request, pk):
        scheduled_message = self.get_object(pk)
        # And we block it if the current DB value is already "scheduled" or "in_progress"
        if scheduled_message.status in ['scheduled', 'scheduled_warning', 'in_progress']:
            return Response(
                {"detail": f"Cannot change status to 'scheduled' when current status is '{scheduled_message.status}'."},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = ScheduledMessageSerializer(scheduled_message, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        scheduled_message = self.get_object(pk)

        # Delete associated Excel files
        if scheduled_message.excel_filename:
            delete_files(scheduled_message.excel_filename.split(','))
        scheduled_message.delete()
        return Response({"detail": "Deleted successfully."}, status=status.HTTP_204_NO_CONTENT)


class ScheduledMessageBulkDeleteAPIView(APIView):
    permission_classes = [EnterpriserUsers]
    def post(self, request):
        serializer = BulkDeleteSerializer(data=request.data)
        enterprise_profile = getattr(self.request.user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        if serializer.is_valid():
            ids = serializer.validated_data['ids']
            messages = ScheduledMessage.objects.filter(id__in=ids, organization_id=organization)

            # Delete associated Excel files for each message
            for message in messages:
                if message.excel_filename:
                    delete_files(message.excel_filename.split(','))

            deleted_count, _ = messages.delete()
            return Response({"detail": f"{deleted_count} records deleted."}, status=status.HTTP_204_NO_CONTENT)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ScheduleMessageHistoryView(APIView):
    permission_classes = [EnterpriserUsers]
    def get(self, request):
        enterprise_profile = getattr(self.request.user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        if not organization:
            return Response({"error": "Organization is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            logs = PlatformLog.objects.filter(organization_id=organization)\
                                      .select_related('scheduled_message', 'recipient')\
                                      .order_by('-created_at')
            serializer = PlatformLogHistorySerializer(logs, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)