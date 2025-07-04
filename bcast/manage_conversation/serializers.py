from rest_framework import serializers
from manage_files.models import File
from .models import Conversation, IncomingMessage, UserMessage


class IncomingMessageSerializer(serializers.ModelSerializer):
    type = serializers.CharField(default='customer')
    media_url = serializers.SerializerMethodField()

    class Meta:
        model = IncomingMessage
        fields = ('id', 'type', 'message_type', 'message_body', 'status', 'status_details', 'received_time', 'media_url')
    
    def get_media_url(self, obj):
        if obj.message_type not in ['text', 'template']:
            file_id = int(obj.status_details) if (obj.status_details.isdigit()) else -1
            if file_id:
                try:
                    file = File.objects.get(id=file_id)
                    if not file.is_signed_url_valid():
                        file.refresh_signed_url()
                    return file.signed_url
                except File.DoesNotExist:
                    return None
        return None

class UserMessageSerializer(serializers.ModelSerializer):
    type = serializers.CharField(default='org')
    sender = serializers.IntegerField(source='user_id')
    media_url = serializers.SerializerMethodField()

    class Meta:
        model = UserMessage
        fields = ('id', 'type', 'message_type', 'message_body', 'status', 'status_details', 'sent_time', 'sender', 'template', 'media_url')
    
    def get_media_url(self, obj):
        if obj.message_type not in ['text'] and obj.status_details not in [None] and obj.status != 'failed':
            file_id = int(obj.status_details) if (obj.status_details.isdigit()) else -1
            if file_id:
                try:
                    file = File.objects.get(id=file_id)
                    if not file.is_signed_url_valid():
                        file.refresh_signed_url()
                    return file.signed_url
                except File.DoesNotExist:
                    return None
        return None

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
        fields = ('id', 'contact', 'assigned', 'organization', 'status', 'created_at', 'updated_at', 'open_by', 'closed_by', 'closed_reason', 'messages')

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