from rest_framework import serializers
from django.db import transaction
from .models import Contact, ContactCustomField, ContactCustomFieldValue, ContactGroup, GroupMember


# serializers.py
class ContactCustomFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactCustomField
        fields = ['id', 'name', 'key', 'field_type', 'required', 'organization']
        read_only_fields = ['organization']

    def validate(self, data):
        request = self.context.get('request')
        if request and request.method in ['POST', 'PUT']:
            data['organization'] = request.user.enterprise_profile.organization
        return data


class ContactCustomFieldValueSerializer(serializers.ModelSerializer):
    key = serializers.CharField(source='custom_field.key')
    field_type = serializers.CharField(source='custom_field.field_type')
    class Meta:
        model = ContactCustomFieldValue
        fields = ['key', 'field_type', 'value']


#class ContactSerializer(serializers.ModelSerializer):
#    custom_fields = ContactCustomFieldValueSerializer(many=True, read_only=True, source='custom_field_values')
#    class Meta:
#        model = Contact
#        fields = ['id', 'name', 'description', 'phone', 'platform_name', 'image', 'address', 'category', 'organization', 'created_by', 'custom_fields']
#        extra_kwargs = {
#            'organization': {'read_only': True},
#            'created_by': {'read_only': True},
#        }
#    def validate(self, data):
#        # Ensure the contact belongs to the user's organization
#        request = self.context['request']
#        if request.method == 'POST':
#            data['organization'] = request.user.enterprise_profile.organization
#            data['created_by'] = request.user
#        return data


class ContactSerializer(serializers.ModelSerializer):
    custom_fields = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = [
            'id', 'name', 'description', 'phone', 'platform_name', 'image',
            'address', 'category', 'organization', 'created_by',
            'custom_fields'
        ]
        extra_kwargs = {
            'organization': {'read_only': True},
            'created_by': {'read_only': True},
        }

    def get_custom_fields(self, obj):
        values = ContactCustomFieldValue.objects.filter(contact=obj)
        return {v.custom_field.key: v.value for v in values}

    def validate(self, data):
        request = self.context['request']
        if request.method == 'POST':
            data['organization'] = request.user.enterprise_profile.organization
            data['created_by'] = request.user
        return data

    def create(self, validated_data):
        request_data = self.context['request'].data
        custom_fields = self.context.get("custom_fields", {}) or request_data.get('custom_fields', {})
        contact = super().create(validated_data)
        self._save_custom_fields(contact, custom_fields)
        return contact

    def update(self, instance, validated_data):
        request_data = self.context['request'].data
        custom_fields = self.context.get("custom_fields", {}) or request_data.get('custom_fields', {})
        contact = super().update(instance, validated_data)
        self._save_custom_fields(contact, custom_fields)
        return contact

    def _save_custom_fields(self, contact, custom_fields):
        org_fields = ContactCustomField.objects.filter(organization=contact.organization)
        field_map = {f.key: f for f in org_fields}

        for key, value in custom_fields.items():
            if key in field_map:
                field = field_map[key]
                ContactCustomFieldValue.objects.update_or_create(
                    contact=contact,
                    custom_field=field,
                    defaults={'value': str(value)}
                )





class GroupMemberSerializer(serializers.ModelSerializer):
    # Use ContactSerializer to display contact details
    contact = ContactSerializer(read_only=True)
    # Accept contact and group IDs for creation
    contact_id = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(), source='contact', write_only=True
    )
    group_id = serializers.PrimaryKeyRelatedField(
        queryset=ContactGroup.objects.all(), source='group', write_only=True
    )

    class Meta:
        model = GroupMember
        fields = ['id', 'group_id', 'contact_id', 'contact']

    def validate(self, data):
        user_org = self.context['request'].user.enterprise_profile.organization

        # Ensure both group and contact belong to the user's organization
        if data['group'].organization != user_org or data['contact'].organization != user_org:
            raise serializers.ValidationError("Group and contact must belong to your organization.")
        return data


class ContactGroupSerializer(serializers.ModelSerializer):
    # Show members using GroupMemberSerializer (read-only)
    members = GroupMemberSerializer(many=True, source='members.all', read_only=True)
    # Allow members to be added using a list of contact IDs
    member_ids = serializers.ListField(
        child=serializers.PrimaryKeyRelatedField(queryset=Contact.objects.all()), write_only=True, required=False
    )

    member_count = serializers.SerializerMethodField()

    class Meta:
        model = ContactGroup
        fields = ['id', 'name', 'description', 'category', 'members', 'member_ids', "member_count"]
    
    def get_member_count(self, obj):
        return obj.members.count()

    def create(self, validated_data):
        request = self.context['request']
        validated_data['organization'] = request.user.enterprise_profile.organization
        validated_data['created_by'] = request.user
        
        member_ids = validated_data.pop('member_ids', [])
        with transaction.atomic():
            # Create group
            group = super().create(validated_data)
            # Add members to the group
            for contact_id in member_ids:
                GroupMember.objects.create(group=group, contact=contact_id, organization=request.user.enterprise_profile.organization)
            return group

    def update(self, instance, validated_data):
        request = self.context['request']
        member_ids = validated_data.pop('member_ids', None)
        with transaction.atomic():
            # Update group details
            group = super().update(instance, validated_data)
            if member_ids is not None:
                # Clear existing members and add new ones
                group.members.all().delete()
                for contact_id in member_ids:
                    GroupMember.objects.create(group=group, contact=contact_id, organization=request.user.enterprise_profile.organization)
            return group




