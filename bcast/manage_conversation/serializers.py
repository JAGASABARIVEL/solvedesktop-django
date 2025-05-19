from rest_framework import serializers
from .models import Conversation, IncomingMessage, UserMessage


class IncomingMessageSerializer(serializers.ModelSerializer):
    type = serializers.CharField(default='customer')

    class Meta:
        model = IncomingMessage
        fields = ('id', 'type', 'message_type', 'message_body', 'status', 'status_details', 'received_time')


class UserMessageSerializer(serializers.ModelSerializer):
    type = serializers.CharField(default='org')
    sender = serializers.IntegerField(source='user_id')

    class Meta:
        model = UserMessage
        fields = ('id', 'type', 'message_type', 'message_body', 'status', 'status_details', 'sent_time', 'sender', 'template')


class ContactSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    phone = serializers.CharField()


class AssignedUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ConversationSerializer(serializers.ModelSerializer):
    messages = serializers.SerializerMethodField()
    contact = ContactSerializer()
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