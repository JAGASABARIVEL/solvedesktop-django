import json
from rest_framework import serializers
from manage_files.models import File
from .models import Conversation, IncomingMessage, UserMessage


class IncomingMessageSerializer(serializers.ModelSerializer):
    type = serializers.CharField(default='customer')
    media_url = serializers.SerializerMethodField()
    media_urls = serializers.SerializerMethodField()

    class Meta:
        model = IncomingMessage
        fields = ('id', 'type', 'message_type', 'message_body', 'content_blocks', 'status', 'status_details', 'received_time', 'media_url', 'media_urls')
    
    def get_media_url(self, obj):
        if obj.message_type not in ['text', 'template', 'text+image'] and obj.status_details and obj.status_details not in [None]:
            file_id = int(obj.status_details) if obj.status_details.isdigit() else -1
            if file_id:
                try:
                    file = File.objects.get(id=file_id)
                    if not file.is_signed_url_valid():
                        file.refresh_signed_url()
                    return file.signed_url
                except File.DoesNotExist:
                    return None
        return None
    def get_media_urls(self, obj):
        urls = []
        try:
            file_ids = json.loads(obj.status_details or "[]")
            type_map = json.loads(obj.message_type or "{}")
            for file_id in file_ids:
                try:
                    file = File.objects.get(id=file_id)
                    if not file.is_signed_url_valid():
                        file.refresh_signed_url()
                    urls.append({
                        "url": file.signed_url,
                        "type": type_map.get(str(file_id), "application/octet-stream"),
                        "filename": file.name
                    })
                except File.DoesNotExist:
                    continue
        except (json.JSONDecodeError, TypeError):
            pass
        return urls



class UserMessageSerializer(serializers.ModelSerializer):
    type = serializers.CharField(default='org')
    sender = serializers.IntegerField(source='user_id')
    media_url = serializers.SerializerMethodField()
    media_urls = serializers.SerializerMethodField()

    class Meta:
        model = UserMessage
        fields = ('id', 'type', 'message_type', 'message_body', 'status', 'status_details', 'sent_time', 'sender', 'template', 'media_url', 'media_urls')
    
    def get_media_url(self, obj):
        if obj.message_type not in ['text', 'text+image'] and obj.status_details and obj.status_details not in [None] and obj.status != 'failed':
            file_id = int(obj.status_details) if obj.status_details.isdigit() else -1
            if file_id:
                try:
                    file = File.objects.get(id=file_id)
                    if not file.is_signed_url_valid():
                        file.refresh_signed_url()
                    return file.signed_url
                except File.DoesNotExist:
                    return None
        return None
    def get_media_urls(self, obj):
        """Supports multiple file IDs (as JSON string) in status_details"""
        urls = []
        try:
            file_ids = json.loads(obj.status_details or "[]")
            type_map = json.loads(obj.message_type or "{}")
            for file_id in file_ids:
                try:
                    file = File.objects.get(id=file_id)
                    if not file.is_signed_url_valid():
                        file.refresh_signed_url()
                    urls.append({
                        "url": file.signed_url,
                        "type": type_map.get(str(file_id), "application/octet-stream"),
                        "filename": file.name
                    })
                except File.DoesNotExist:
                    continue
        except (json.JSONDecodeError, TypeError):
            pass
        return urls

from manage_contact.models import Contact, ContactCustomFieldValue
class ContactCustomFieldValueSerializer(serializers.ModelSerializer):
    key = serializers.CharField(source='custom_field.key')
    field_type = serializers.CharField(source='custom_field.field_type')

    class Meta:
        model = ContactCustomFieldValue
        fields = ['key', 'field_type', 'value']


class ContactWithCustomFieldsSerializer(serializers.ModelSerializer):
    custom_fields = ContactCustomFieldValueSerializer(many=True, read_only=True, source='custom_field_values')

    class Meta:
        model = Contact
        fields = ['id', 'name', 'phone', 'platform_name', 'image', 'address', 'category', 'description', 'custom_fields']


class AssignedUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ConversationSerializer(serializers.ModelSerializer):
    messages = serializers.SerializerMethodField()
    contact = ContactWithCustomFieldsSerializer()  # updated!
    assigned = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ('id', 'contact', 'assigned', 'organization', 'status', 'subject', 'created_at', 'updated_at', 'open_by', 'closed_by', 'closed_reason', 'messages')

    def get_assigned(self, obj):
        if obj.assigned_user:
            return AssignedUserSerializer({'id': obj.assigned_user.id, 'name': obj.assigned_user.username}).data
        return None

    def get_messages(self, obj):
        incoming_msgs = IncomingMessage.objects.filter(conversation=obj)
        user_msgs = UserMessage.objects.filter(conversation=obj)

        incoming_data = IncomingMessageSerializer(incoming_msgs, many=True).data
        user_data = UserMessageSerializer(user_msgs, many=True).data

        # Combine and sort by timestamp
        combined_messages = incoming_data + user_data
        combined_messages.sort(key=lambda x: x['received_time'] if x['type'] == 'customer' else x['sent_time'])
        return combined_messages
