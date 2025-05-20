
import json
from datetime import datetime, timedelta, time, date
from dateutil.relativedelta import relativedelta
from collections import defaultdict
import mimetypes

from django.db.models import Count, Case, When, F, Avg, Q
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.utils.timezone import now, make_aware
from django.conf import settings

from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError

import boto3

from .models import Conversation, UserMessage, IncomingMessage
from manage_users.models import CustomUser, EnterpriseProfile
from manage_platform.models import Platform
from manage_contact.models import Contact
from manage_users.permissions import EnterpriserUsers

from .serializers import ConversationSerializer

from VendorApi.Whatsapp.message import MediaMessage, TextMessage, TemplateMessage, WebHookException, SendException
from VendorApi.Webchat.message import TextMessage as webTextMessage


User = get_user_model()
from botocore.client import Config
s3 = boto3.client(
    's3',
    endpoint_url=settings.B2_ENDPOINT_URL,
    aws_access_key_id=settings.B2_ACCESS_KEY_ID,
    aws_secret_access_key=settings.B2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
)

ALLOWED_MIME_TYPES = {
    "image": ["image/jpeg", "image/png"],
    "video": ["video/mp4", "video/3gpp"],
    "audio": ["audio/aac", "audio/mpeg", "audio/amr", "audio/ogg"],
    "document": [
        "application/pdf",
        "application/vnd.ms-excel",
        "application/msword",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ]
}

def get_media_type_from_mime(mime_type):
    for media_type, types in ALLOWED_MIME_TYPES.items():
        if mime_type in types:
            return media_type
    return None

def send_message(platform_id, recipient_id, message_body, template=None, message_type="text", **kwargs):
    try:
        platform = Platform.objects.get(id=platform_id)
        platform_name = platform.platform_name
        phone_number_id = platform.login_id
        token = platform.login_credentials
        recipient_phone_number = Contact.objects.get(id=recipient_id).phone
        if platform_name.startswith('whatsapp'):
            print(
                "Message Sent!!\n",
                "Platform : ", platform_name, "\n",
                "Login Id : ", phone_number_id, "\n",
                "From Key : ", token, "\n",
                "Recipient : ", recipient_phone_number, "\n",
                "Message : ", message_body, "\n",
            )
            if message_type == "text":
                text_message = TextMessage(
                    phone_number_id=phone_number_id,
                    token=token,
                    client_application='REG_APP_NAME'
                )
                response = text_message.send_message(recipient_phone_number, message_body)
                return response
            elif message_type == "template":
                approved_templates = TemplateMessage(
                    waba_id=platform.app_id,
                    phone_number_id=platform.login_id,
                    token=platform.login_credentials
                )
                response = approved_templates.send_message(recipient_phone_number, message_body, template)
                return response
            elif message_type == "media":
                media_message = MediaMessage(
                    phone_number_id=platform.login_id,
                    token=platform.login_credentials
                )
                caption = message_body if kwargs.get("media_type") in ["image", "video", "document"] else None
                response = media_message.send_media_message(
                    recipient_phone_number,
                    kwargs.get("media_file"),
                    kwargs.get("media_type"),
                    kwargs.get("mime_type"),
                    caption=caption
                )
                return response
        elif platform_name == "webchat":
            print("Sending message in webchat platform to ", {recipient_phone_number, message_body})
            text_message = webTextMessage(
                token=token,
            )
            response = text_message.send_message(recipient_phone_number, message_body)
            conversation = kwargs.get('conversation')
            print("conversation ", conversation)
            with transaction.atomic():
                # Right now we dont have anyother way to confirm the delivery since its through websocket and not webhook to confirm the delivery
                incoming_messages = IncomingMessage.objects.filter(conversation=conversation).update(status='responded')
            return response
        else:
            raise ValueError(f"Unsupported platform {platform_name}")
    except WebHookException as webhook_error:
        raise RuntimeError(f"Webhook error - failed to read notification: {str(webhook_error)}")
    except SendException as send_error:
        raise RuntimeError(f"Whatsapp error - failed to send message: {str(send_error)}")
    except Exception as e:
        raise RuntimeError(f"Failed to send message: {str(e)}")


def format_template_messages(template, parameters_body):
    if isinstance(template, str):
        template = json.loads(template)
    for component in template.get('components'):
        for buffer in parameters_body.keys():
            try:
                parameter_index = component["text"].index(buffer)
                start_index = parameter_index - 2 # {{
                end_index = parameter_index + len(buffer) + 2 # parameter_name}}
                component["text"] = component["text"].replace(component["text"][start_index : end_index], parameters_body[buffer])
            except ValueError:
                continue
    return template


from manage_files.models import File, FileStorageEvent, FilePermission
class ConversationViewSet(viewsets.ModelViewSet):
    queryset = Conversation.objects.all().select_related('assigned_user', 'contact')
    serializer_class = ConversationSerializer
    permission_classes = [EnterpriserUsers]

    def get_queryset(self):
        user = self.request.user
        status = self.request.query_params.get('status', None)
        is_user_specific = self.request.query_params.get('is_user_specific', None)
        # Get the organization via the EnterpriseProfile model
        enterprise_profile = getattr(user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        self.queryset = self.queryset.filter(organization=organization)
        if status:
            self.queryset = self.queryset.filter(status=status)
        if is_user_specific == "true":
            self.queryset = self.queryset.filter(assigned_user=user)
        return self.queryset
    
    @action(detail=False, methods=['get'])
    def active_conversation_for_org(self, request, pk=None):
        """Retrieve conversations with status 'active' or 'new' for the logged-in user"""
        enterprise_profile = getattr(self.request.user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        conversations = Conversation.objects.filter(
            organization=organization,
            status__in=['active', 'new']  # Filters both active and new status
        )
        serializer = ConversationSerializer(conversations, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def active_conversation_for_user(self, request, pk=None):
        """Retrieve conversations with status 'active' or 'new' for the logged-in user"""
        conversations = Conversation.objects.filter(
            assigned_user=request.user.id,
            status__in=['active', 'new']  # Filters both active and new status
        )
        serializer = ConversationSerializer(conversations, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def all_conversation_for_user(self, request, pk=None):
        """Retrieve conversations with status 'active' or 'new' for the logged-in user"""
        conversations = Conversation.objects.filter(
            assigned_user=request.user.id,
            status__in=['active', 'new', 'closed']  # Filters both active and new status
        )
        serializer = ConversationSerializer(conversations, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def history_by_contact(self, request):
        """Retrieve all conversation history for a given contact ID"""
        contact_id = request.query_params.get("contact_id")  # Fetch from query params
        if not contact_id:
            return Response({"error": "contact_id is required"}, status=400)

        conversations = Conversation.objects.filter(contact_id=contact_id).order_by("-created_at")
        serializer = ConversationSerializer(conversations, many=True)
        return Response(serializer.data)

    #@action(detail=True, methods=['post'])
    #def start_conversation(self, request, pk=None):
    #    conversation = get_object_or_404(Conversation, pk=pk)
    #    if conversation.status == 'closed':
    #        conversation.status = 'active'
    #        conversation.save()
    #    return Response({'status': 'conversation started'})

    @action(detail=True, methods=['post'])
    def close_conversation(self, request, pk=None):
        conversation = get_object_or_404(Conversation, pk=pk)
        conversation.status = 'closed'
        conversation.assigned_user = request.user
        conversation.closed_by = request.user
        conversation.closed_reason = request.data.get('reason', '')
        conversation.save()
        return Response({'status': 'conversation closed'})
    
    @action(detail=True, methods=['post'])
    def assign_conversation(self, request, pk=None):
        conversation = get_object_or_404(Conversation, pk=pk)
        user_id = request.data.get('id')

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        conversation.assigned_user = user
        conversation.status = 'active'
        conversation.updated_at = now()
        conversation.save()
        return Response({
            'message': 'Conversation assigned successfully',
            'conversation_id': conversation.id,
            'assigned_user_id': user.id
        })

    @action(detail=True, methods=['post'])
    def respond_to_message(self, request, pk=None):    
        conversation = get_object_or_404(Conversation, pk=pk)
        user = request.user
        enterprise_profile = getattr(user, "enterprise_profile", None)
        org = getattr(enterprise_profile, "organization", None)
        owner_user = org.owner
        platform = conversation.platform
        recipient_phone_number = conversation.contact.phone
        if conversation.status == 'closed':
            return Response({'error': 'Cannot respond to a closed conversation'}, status=status.HTTP_400_BAD_REQUEST)
        conversation.status = 'active'
        conversation.updated_at = now()
        conversation.save()
        media_file = request.FILES.get('file')
        mime_type, _ = mimetypes.guess_type(media_file.name) if media_file else (None, None)
        media_type = get_media_type_from_mime(mime_type) if mime_type else None
        message_body = request.POST.get('message_body') or request.data.get('message_body')
        template = request.POST.get('template') or request.data.get('template')
        file_instance = None
        message_type = "text"
        try:
            response = None
            if media_file and media_type:
                message_type = mime_type
                # Send the message after uploading
                response = send_message(
                    platform_id=conversation.platform_id,
                    recipient_id=conversation.contact_id,
                    message_body=message_body,
                    template=template,
                    message_type="media",
                    media_file=media_file, media_type=media_type, mime_type=mime_type
                )
                try:
                    # Prepare variables
                    file_size = media_file.size
                    size_gb = file_size / (1024 ** 3)
                    uname = owner_user.email.split('@')[0]
                    org_name = conversation.organization.name.replace(" ", "_")
                    receiver_name = Contact.objects.get(id=conversation.contact_id).phone
                    receiver_directory = receiver_name.replace(" ", "_")
                    today_str = date.today().isoformat()
                    filename = media_file.name
                    customer_directory = "customer"
                    sent_directory_name = "sent"

                    # Generate S3 keys
                    home_directory_key = f"{uname}/"
                    org_directory_key = f"{home_directory_key}{org_name}/"
                    customer_directory_key = f"{org_directory_key}{customer_directory}/"
                    sent_directory_key = f"{customer_directory_key}{sent_directory_name}/"
                    receiver_folder_key = f"{sent_directory_key}{receiver_directory}/"
                    date_folder_key = f"{receiver_folder_key}{today_str}/"
                    file_key = f"{date_folder_key}{filename}"
                    # Upload placeholders for folders and file
                    s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=home_directory_key)
                    s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=org_directory_key)
                    s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=customer_directory_key)
                    s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=sent_directory_key)
                    s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=receiver_folder_key)
                    s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=date_folder_key)
                    s3.upload_fileobj(media_file, settings.AWS_STORAGE_BUCKET_NAME, file_key)

                    # Folder: Username
                    home_directory, _ = File.objects.get_or_create(
                        s3_key=home_directory_key,
                        owner=owner_user,
                        defaults={
                            'name': uname,
                            'parent': None,
                            'size_gb': 0,
                            'created_at': now(),
                            'is_deleted': False
                        }
                    )
                    home_directory.is_deleted = False
                    home_directory.save()

                    # Folder: Orgname
                    org_directory, _ = File.objects.get_or_create(
                        s3_key=org_directory_key,
                        owner=owner_user,
                        defaults={
                            'name': org_name,
                            'parent': home_directory,
                            'size_gb': 0,
                            'created_at': now(),
                            'is_deleted': False
                        }
                    )
                    org_directory.is_deleted = False
                    org_directory.save()

                    

                    # Folder: Customer
                    customer_home_directory, _ = File.objects.get_or_create(
                        s3_key=customer_directory_key,
                        owner=owner_user,
                        defaults={
                            'name': customer_directory,
                            'parent': org_directory,
                            'size_gb': 0,
                            'created_at': now(),
                            'is_deleted': False
                        }
                    )
                    customer_home_directory.is_deleted = False
                    customer_home_directory.save()

                    # Folder: Sent Directory
                    sent_directory, _ = File.objects.get_or_create(
                        s3_key=sent_directory_key,
                        owner=owner_user,
                        defaults={
                            'name': sent_directory_name,
                            'parent': customer_home_directory,
                            'size_gb': 0,
                            'created_at': now(),
                            'is_deleted': False
                        }
                    )
                    sent_directory.is_deleted = False
                    sent_directory.save()

                    # Folder: Receiver
                    receiver_folder, _ = File.objects.get_or_create(
                        s3_key=receiver_folder_key,
                        owner=owner_user,
                        defaults={
                            'name': receiver_directory,
                            'parent': sent_directory,
                            'size_gb': 0,
                            'created_at': now(),
                            'is_deleted': False
                        }
                    )
                    receiver_folder.is_deleted = False
                    receiver_folder.save()

                    # Folder: Date under Receiver
                    date_folder, _ = File.objects.get_or_create(
                        s3_key=date_folder_key,
                        owner=owner_user,
                        defaults={
                            'name': today_str,
                            'parent': receiver_folder,
                            'size_gb': 0,
                            'created_at': now(),
                            'is_deleted': False
                        }
                    )
                    date_folder.is_deleted = False
                    date_folder.save()

                    # Actual File under Date folder
                    file_instance = File.objects.create(
                        name=filename,
                        owner=owner_user,
                        s3_key=file_key,
                        parent=date_folder,
                        size_gb=size_gb,
                    )
                    # Create FileStorageEvent
                    FileStorageEvent.objects.create(
                        user=owner_user,
                        file_id=file_instance,
                        file_name=file_instance.name,
                        size_gb=size_gb
                    )

                    employees_of_org = EnterpriseProfile.objects.filter(organization=org).all()
                    for employee in employees_of_org:
                        employee_user = employee.user
                        if employee_user.id == owner_user.id:
                            continue                        
                        permission, created = FilePermission.objects.update_or_create(
                            file=file_instance,
                            user=employee_user,
                            defaults={"can_read": True, "can_write": True}
                        )
                        permission.save()
                except Exception as e:
                    import traceback
                    traceback.print_exc()
            else:
                message_type = "text"
                response = send_message(
                    platform_id=conversation.platform_id,
                    recipient_id=conversation.contact_id,
                    message_body=message_body,
                    template=template,
                    message_type=message_type,
                    conversation=conversation
                )
            message_id = response.json().get('messages', [{}])[0].get('id', 'unknown') if response else None
            status_value = 'sent_to_server'
            error_message = None
        except Exception as e:
            message_id = 'Cannot send'
            status_value = 'failed'
            error_message = str(e)
        file_id = file_instance.id if file_instance else None
        UserMessage.objects.create(
            conversation=conversation,
            organization=conversation.organization,
            platform=platform,
            user=user,
            message_body=message_body,
            status=status_value,
            messageid=message_id,
            template=template,
            status_details=error_message or file_id, # Using status_dertauls to persists file id since it would None if there are no errors
            message_type=message_type
        )
        if status_value == 'failed':
            return Response({'error': 'Failed to deliver the message', 'details': error_message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({'status': 'success', 'message': 'Response logged successfully'})

    
    @action(detail=False, methods=['post'])
    def new_conversation(self, request):
        user = request.user
        enterprise_profile = getattr(user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        platform_id = request.data.get('platform_id')
        contact_id = request.data.get('contact_id')
        template = request.data.get('template')
        message_body = request.data.get('template_parameters', {})
        template_body = [{"type": "text", "parameter_name": key,  "text": value} for key, value in message_body.items()] or None
        conversation = Conversation.objects.filter(
            organization=organization,
            platform_id=platform_id,
            contact_id=contact_id,
            status__in=['new', 'active']
        ).first()
        if conversation:
            return Response({'error': 'Conversation already open / active'}, status=status.HTTP_400_BAD_REQUEST)
        conversation = Conversation.objects.create(
            organization=organization,
            platform_id=platform_id,
            contact_id=contact_id,
            assigned_user=user,
            open_by=user.username,
            status="active"
        )
        try:
            response = send_message(
                platform_id=platform_id,
                recipient_id=contact_id,
                message_body=template_body,
                template=template,
                message_type="template"
            )
            message_id = response.json().get('messages', [{}])[0].get('id', 'unknown')
        except Exception as e:
            UserMessage.objects.create(
                conversation=conversation,
                organization=organization,
                platform_id=platform_id,
                user=user,
                message_body=message_body,
                status='failed',
                status_details=str(e),
                messageid="Cannot send",
                template=json.dumps(format_template_messages(template, message_body))
            )
            return Response({'error': 'Failed to deliver the message'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        UserMessage.objects.create(
            conversation=conversation,
            organization=organization,
            platform_id=platform_id,
            user=user,
            message_body=message_body,
            status='sent_to_server',
            messageid=message_id,
            template=json.dumps(format_template_messages(template, message_body))
        )
        return Response({'id': conversation.id}, status=status.HTTP_200_OK)


class DateRangeHelper:
    @staticmethod
    def get_date_range(filter_type):
        today = datetime.today()
        ranges = {
            'daily': (today - timedelta(days=1), today),
            'weekly': (today - timedelta(days=7), today),
            'monthly': (today - timedelta(days=30), today),
            'quarterly': (today - timedelta(days=90), today),
            'halfyearly': (today - timedelta(days=180), today),
            'yearly': (today - timedelta(days=365), today)
        }
        if filter_type not in ranges:
            raise ValidationError("Invalid filter type. Must be 'daily', 'weekly', 'monthly', etc.")
        return ranges[filter_type]

    @staticmethod
    def get_grouping_interval(filter_type):
        intervals = {
            'daily': 'updated_at__date',
            'weekly': 'updated_at__week',
            'monthly': 'updated_at__month',
            'quarterly': 'updated_at__quarter',
            'halfyearly': 'updated_at__half_year',
            'yearly': 'updated_at__year'
        }
        if filter_type not in intervals:
            raise ValidationError("Invalid filter type")
        return intervals[filter_type]

class OrganizationConversationMetricsAPIView(APIView):
    permission_classes = [EnterpriserUsers]
    def get(self, request):
        # Ensure the user has an organization
        enterprise_profile = getattr(self.request.user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        if not organization:
            return Response({'error': 'Organization is required'}, status=status.HTTP_400_BAD_REQUEST)

        duration = request.query_params.get('duration', None)
        period = request.query_params.get('period', 'daily')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if duration:
            start_date, end_date = DateRangeHelper.get_date_range(duration)
        else:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        start_date = datetime.combine(start_date, time.min)
        end_date = datetime.combine(end_date, time.max)
        conversations = Conversation.objects.filter(
            organization_id=organization.id,
            #assigned_user_id__isnull=False,
            updated_at__range=(start_date, end_date)
        )
        grouping_interval = DateRangeHelper.get_grouping_interval(period)
        stats = conversations.values(grouping_interval).annotate(
            total_assigned=Count('id'),
            total_closed=Count(Case(When(status='closed', then=1))),
            total_active=Count(Case(When(status='active', then=1)))
        ).order_by(grouping_interval)

        return Response({
            'org_performance_stats': [
                {
                    'label': stat[grouping_interval],
                    'total_assigned': stat['total_assigned'],
                    'total_closed': stat['total_closed'],
                    'total_active': stat['total_active']
                } for stat in stats
            ]
        })

class EmployeeConversationMetricsAPIView(APIView):
    permission_classes = [EnterpriserUsers]
    def get(self, request):
        duration = request.query_params.get('duration', None)
        period = request.query_params.get('period', 'daily')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        user_id = request.query_params.get('user_id', self.request.user.id)

        user = CustomUser.objects.filter(id=user_id).first()
        enterprise_profile = getattr(user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        if not organization:
            return Response({'error': 'Organization is required'}, status=status.HTTP_400_BAD_REQUEST)

        if duration:
            start_date, end_date = DateRangeHelper.get_date_range(duration)
        else:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        start_date = datetime.combine(start_date, time.min)
        end_date = datetime.combine(end_date, time.max)

        conversations = Conversation.objects.filter(
            organization_id=organization.id,
            updated_at__range=(start_date, end_date)
        )
        grouping_interval = DateRangeHelper.get_grouping_interval(period)

        stats = conversations.values(grouping_interval, 'assigned_user_id').annotate(
            total_assigned=Count('id'),
            total_closed=Count(Case(When(status='closed', then=1))),
            total_active=Count(Case(When(status='active', then=1)))
        ).order_by(grouping_interval)
        return Response({
            'user_performance_stats': [
                {
                    'label': stat[grouping_interval],
                    'assigned_user_id': stat['assigned_user_id'],
                    'total_assigned': stat['total_assigned'],
                    'total_closed': stat['total_closed'],
                    'total_active': stat['total_active']
                } for stat in stats
            ]
        })

from django.db.models import Subquery, OuterRef, Avg, F, Q

class ConversationStatsAPIView(APIView):
    permission_classes = [EnterpriserUsers]

    def get(self, request):
        enterprise_profile = getattr(self.request.user, "enterprise_profile", None)
        organization = getattr(enterprise_profile, "organization", None)
        if not organization:
            return Response({'error': 'Organization is required'}, status=status.HTTP_400_BAD_REQUEST)
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)

        # Query for conversation counts
        total_new = Conversation.objects.filter(organization_id=organization.id).count()
        total_closed = Conversation.objects.filter(
            organization_id=organization.id, status='closed',
            updated_at__range=(start_date, end_date)
        ).count()
        total_active = Conversation.objects.filter(
            organization_id=organization.id, status='active',
            updated_at__range=(start_date, end_date)
        ).count()

        # Per contact statistics
        per_contact_stats = Conversation.objects.filter(
            organization_id=organization.id, updated_at__range=(start_date, end_date)
        ).values('contact_id').annotate(
            communication_count=Count('id'),
            services_used=Count('platform_id', distinct=True)
        )

        services_used_stats = Conversation.objects.filter(
            organization_id=organization.id, updated_at__range=(start_date, end_date)
        ).values('contact_id', 'platform_id').annotate(conversation_count=Count('id'))

        platform_names = dict(Platform.objects.values_list('id', 'platform_name'))

        # User performance statistics
        user_performance_stats = Conversation.objects.filter(
            organization_id=organization.id,
            updated_at__range=(start_date, end_date)
        ).values('assigned_user_id').annotate(
            total_active=Count('id', filter=Q(status='active')),
            total_closed=Count('id', filter=Q(status='closed'))
        ).order_by('-total_closed')

        # Average response time
        latest_received_time = IncomingMessage.objects.filter(
            conversation=OuterRef('conversation')
        ).order_by('-received_time').values('received_time')[:1]  # Get latest received time
        
        average_response_time = UserMessage.objects.filter(
            sent_time__gt=Subquery(latest_received_time),
            conversation__organization_id=organization.id
        ).aggregate(avg_response_time=Avg(
            F('sent_time') - Subquery(latest_received_time)
        ))['avg_response_time']

        # Get the latest received message time per conversation
        latest_received_time = IncomingMessage.objects.filter(
            conversation=OuterRef('conversation')
        ).order_by('-received_time').values('received_time')[:1]  # Fetch latest received_time
        
        # Response time per employee
        response_time_per_employee = UserMessage.objects.filter(
            sent_time__gt=Subquery(latest_received_time),
            conversation__organization_id=organization.id
        ).values('user_id').annotate(
            avg_response_time=Avg(F('sent_time') - Subquery(latest_received_time))
        )
        
        # Average resolution time
        resolution_time = UserMessage.objects.filter(
            conversation__status='closed',
            conversation__organization_id=organization.id
        ).aggregate(avg_resolution_time=Avg(
            F('sent_time') - Subquery(latest_received_time)
        ))['avg_resolution_time']

        # Average resolution rate
        resolution_rate = Conversation.objects.filter(
            organization_id=organization.id,
            #assigned_user_id__isnull=False,
            updated_at__range=(start_date, end_date)
        ).values('assigned_user_id').annotate(
            resolution_rate=Avg(Case(When(status='closed', then=1), default=0))
        ).aggregate(avg_resolution_rate=Avg('resolution_rate'))['avg_resolution_rate']
        # Resolution time per employee
        resolution_time_per_employee = UserMessage.objects.filter(
            conversation__status='closed',
            conversation__organization_id=organization.id
        ).values('user_id').annotate(
            avg_resolution_time=Avg(F('sent_time') - Subquery(latest_received_time))
        )

        # Structure the response
        response = {
            'total_new': total_new,
            'total_closed': total_closed,
            'total_active': total_active,
            'customer_performance_stats': [
                {
                    'contact_id': stat['contact_id'],
                    'services_used': [
                        {
                            'platform_name': platform_names.get(service['platform_id'], 'Unknown'),
                            'conversation_count': service['conversation_count']
                        } for service in services_used_stats if service['contact_id'] == stat['contact_id']
                    ]
                } for stat in per_contact_stats
            ],
            'user_performance_stats': list(user_performance_stats),
            'user_performance_stats_avg': {
                'average_response_time': round(average_response_time.total_seconds() / 3600, 2) if average_response_time else 0,
                'response_time_per_employee': list(response_time_per_employee),
                'average_resolution_rate': round(resolution_rate * 100, 2) if resolution_rate else 0,
                'average_resolution_time': round(resolution_time.total_seconds() / 3600, 2) if resolution_time else 0,
                'resolution_time_per_employee': list(resolution_time_per_employee),
            }
        }
        return Response(response)


class MessagingCostReportView(APIView):
    permission_classes = [EnterpriserUsers]

    def get(self, request):
        user = request.user
        enterprise_profile = getattr(user, "enterprise_profile", None)
        org = getattr(enterprise_profile, "organization", None)

        try:
            from_date_str = request.query_params.get("from_date")
            to_date_str = request.query_params.get("to_date")

            if not from_date_str or not to_date_str:
                return Response({"error": "from_date and to_date are required (format: YYYY-MM-DD)"}, status=400)

            from_date = make_aware(datetime.strptime(from_date_str, "%Y-%m-%d"))
            to_date = make_aware(datetime.strptime(to_date_str, "%Y-%m-%d")) + timedelta(days=1)
        except Exception as e:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        conversations = Conversation.objects.filter(
            organization=org,
            created_at__range=(from_date, to_date)
        ).select_related("contact")

        customer_convos = conversations.filter(open_by="customer")
        business_convos = conversations.exclude(open_by="customer")

        # Tiered pricing logic
        total_customer_convos = customer_convos.count()
        free_tier = settings.CONVERSATION_FREE_TIER_LIMIT
        charged_customer_convos = max(total_customer_convos - free_tier, 0)

        cost_customer = charged_customer_convos * settings.CONVERSATION_COSTS["customer_initiated"]
        cost_business = business_convos.count() * settings.CONVERSATION_COSTS["business_initiated"]
        total_cost = cost_customer + cost_business

        # Per-contact breakdown
        contact_breakdown = defaultdict(lambda: {"customer_initiated": 0, "business_initiated": 0})

        for convo in customer_convos:
            contact_breakdown[convo.contact_id]["customer_initiated"] += 1

        for convo in business_convos:
            contact_breakdown[convo.contact_id]["business_initiated"] += 1

        breakdown = []
        remaining_free_tier = free_tier
        for contact_id, data in contact_breakdown.items():
            contact = Contact.objects.filter(id=contact_id).first()
            if not contact:
                continue

            # Calculate customer-initiated cost using available free tier
            chargeable_customer = max(data["customer_initiated"] - remaining_free_tier, 0)
            remaining_free_tier -= max(data["customer_initiated"] - chargeable_customer, 0)

            cost = (
                chargeable_customer * settings.CONVERSATION_COSTS["customer_initiated"] +
                data["business_initiated"] * settings.CONVERSATION_COSTS["business_initiated"]
            )

            breakdown.append({
                "contact_name": contact.name,
                "phone": contact.phone,
                "customer_initiated": data["customer_initiated"],
                "business_initiated": data["business_initiated"],
                "cost": round(cost, 2)
            })

        return Response({
            "date_range": f"{from_date_str} to {to_date_str}",
            "total_cost": round(total_cost, 2),
            "customer_conversations": total_customer_convos,
            "business_conversations": business_convos.count(),
            "breakdown": breakdown
        })


class UnrespondedConversationNotificationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        # Filter conversations assigned to the current user with unresponded messages
        conversations = Conversation.objects.filter(
            assigned_user=request.user,
            incoming_messages__status__in=['unread', 'read']
        ).distinct()

        notifications = []

        for convo in conversations:
            # Get last unresponded message in this conversation
            last_msg = convo.incoming_messages.filter(
                status__in=['unread', 'read']
            ).order_by('-received_time').first()

            if last_msg:
                notifications.append({
                    'conversation_id': convo.id,
                    'contact_id': convo.contact_id,
                    'contact_name': str(convo.contact),
                    'last_message': {
                        'message_body': last_msg.message_body,
                        'received_time': last_msg.received_time,
                        'status': last_msg.status
                    }
                })

        return Response({
            'conversation_count': len(notifications),
            'notifications': notifications
        })
