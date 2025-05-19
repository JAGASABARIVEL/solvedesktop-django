# serializers.py
from rest_framework import serializers
from .models import ScheduledMessage, PlatformLog

from rest_framework import serializers
from .models import ScheduledMessage
from manage_contact.models import Contact, ContactGroup

class ScheduledMessageSerializer(serializers.ModelSerializer):
    recipient_name = serializers.SerializerMethodField()
    created_by = serializers.CharField(source='user.username', read_only=True)
    platform_name = serializers.CharField(source='platform.platform_name', read_only=True)

    class Meta:
        model = ScheduledMessage
        fields = '__all__'  # OR list fields explicitly if you want
        extra_fields = ['recipient_name', 'created_by', 'platform_name']

    def get_recipient_name(self, obj):
        if obj.recipient_type == 'individual':
            try:
                contact = Contact.objects.get(id=obj.recipient_id)
                return contact.name
            except Contact.DoesNotExist:
                return None
        elif obj.recipient_type == 'group':
            try:
                group = ContactGroup.objects.get(id=obj.recipient_id)
                return group.name
            except ContactGroup.DoesNotExist:
                return None
        return None



class BulkDeleteSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), required=True)


class PlatformLogHistorySerializer(serializers.ModelSerializer):
    schedule_name = serializers.CharField(source='scheduled_message.name', read_only=True)
    send_date = serializers.DateTimeField(source='scheduled_message.updated_at', read_only=True)
    recipient_name = serializers.CharField(source='recipient.name', read_only=True)
    
    class Meta:
        model = PlatformLog
        fields = ['id', 'schedule_name', 'recipient_name', 'send_date', 'status', 'log_message']
