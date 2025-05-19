from rest_framework import serializers
from django.db import transaction
from .models import Contact, ContactGroup, GroupMember


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ['id', 'name', 'description', 'phone', 'image', 'address', 'category', 'organization', 'created_by']
        extra_kwargs = {
            'organization': {'read_only': True},
            'created_by': {'read_only': True},
        }
    def validate(self, data):
        # Ensure the contact belongs to the user's organization
        request = self.context['request']
        if request.method == 'POST':
            data['organization'] = request.user.enterprise_profile.organization
            data['created_by'] = request.user
        return data


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




