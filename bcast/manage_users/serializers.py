from rest_framework import serializers
from .models import CustomUser, OwnerAccount, EnterpriseProfile
from manage_platform.models import Platform
from manage_organization.models import Organization

from django.db import transaction

class CustomUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "email", "username"]

class EnterpriseSerializer(serializers.ModelSerializer):
    details = CustomUserSerializer(source="user", read_only=True)
    role = serializers.SerializerMethodField()
    class Meta:
        model = EnterpriseProfile
        fields = ["id", "user", "details", "role"]
        extra_kwargs = {"user": {"read_only": True}}  # Hide password from responses
    
    def get_role(self, obj):
        user = obj.user
        #organization = getattr(obj, "organization", None)
        #if organization and hasattr(organization, "owner"):
        #    return "owner" if organization.owner == user else "employee"
        #return "individual"
        if user.is_superuser:
            return "root"
        return user.user_type

class UserRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "email", "phone_number", "password"]
        extra_kwargs = {"password": {"write_only": True}}  # Hide password from responses

    def create(self, validated_data):
        user = CustomUser.objects.create_user(**validated_data)
        return user

class UserLoginSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "phone_number", "password"]
        extra_kwargs = {"password": {"write_only": True}}  # Hide password from responses

class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "phone_number", "email"]

# Updated Serializers

class EnterpriseOwnerRegistrationSerializer(serializers.Serializer):
    organization_name = serializers.CharField(required=True)
    uuid = serializers.CharField(required=False, allow_blank=True)

    platform_name = serializers.ChoiceField(choices=Platform.PLATFORM_CHOICES, required=True)
    friendly_platform_name = serializers.CharField(required=True)
    login_id = serializers.CharField(required=True)
    app_id = serializers.CharField(required=True)
    login_credentials = serializers.CharField(required=True)

    def validate(self, data):
        # Ensure user is authenticated
        if not self.context['request'].user.is_authenticated:
            raise serializers.ValidationError("User must be authenticated.")
        # Ensure user isn't already registered
        if self.context['request'].user.is_registration_complete:
            raise serializers.ValidationError("Registration already completed.")
        return data

    def create(self, validated_data):
        user = self.context['request'].user
        try:
            # Ensure all DB operations are atomic (if one fails, all are rolled back)
            with transaction.atomic():
                # Create Organization
                organization = Organization.objects.create(
                    name=validated_data['organization_name'],
                    owner=user
                )
                # Create EnterpriseProfile
                EnterpriseProfile.objects.create(
                    user=user,
                    organization=organization,
                    uuid=validated_data.get('uuid'),
                )
                # Create OwnerAccount
                OwnerAccount.objects.create(user=user, organization=organization)
                # Create Platform Configuration
                Platform.objects.create(
                    owner=user,
                    organization=organization,
                    platform_name=validated_data['platform_name'],
                    user_platform_name=validated_data['friendly_platform_name'],
                    login_id=validated_data['login_id'],
                    app_id=validated_data['app_id'],
                    login_credentials=validated_data['login_credentials'],  # Consider encrypting this.
                    secret_key=validated_data['secret_key']
                )
                # Update User - Mark registration complete
                user.is_registration_complete = True
                user.user_type = 'owner'
                user.save()
            return user
        except Exception as e:
            # Rollback happens automatically if an exception is raised
            raise serializers.ValidationError(f"Registration failed: {str(e)}")


class EmployeeRegistrationSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    uuid = serializers.CharField(required=False, allow_null=True)
    #organization = serializers.PrimaryKeyRelatedField(queryset=Organization.objects.all(), required=True)

    def validate(self, attrs):
        employee_id = attrs.get("employee_id")
        if not employee_id:
            raise serializers.ValidationError("Employee field is mandatory")        
        employee_user = CustomUser.objects.filter(id=employee_id).first()
        if employee_user.is_superuser:
            raise serializers.ValidationError(f"Emplyoee '{employee_user.email}' is not allowed to be part of any organiztion")
        if employee_user.user_type in {"owner", "agent"}:
            raise serializers.ValidationError(f"Owner / Agent '{employee_user.email}' is not allowed to be added as an employee")
        enterprise_user = EnterpriseProfile.objects.filter(user_id=employee_id).first()
        if enterprise_user:
            raise serializers.ValidationError("Employee already part of the organization")
        return attrs

    def create(self, validated_data):
        try:
            with transaction.atomic():
                uuid = validated_data.get('uuid', None)
                employee_id = validated_data.get('employee_id', None)
                # Retrieve user and data
                user = self.context['request'].user
                employee_user = CustomUser.objects.filter(id=employee_id).first()
                enterprise_profile = getattr(user, "enterprise_profile", None)
                organization = getattr(enterprise_profile, "organization", None)
                # Update or create the EnterpriseProfile
                EnterpriseProfile.objects.update_or_create(
                    user=employee_user,
                    defaults={
                        'organization': organization,
                        'uuid': uuid,
                    },
                )
                # Ensure user is marked as an employee and registration is complete
                employee_user.user_type = 'employee'
                employee_user.is_registration_complete = True
                employee_user.save()
                return employee_user
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise serializers.ValidationError(f"Registration failed: {str(e)}")


class IndividualRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["id", "email", "username", "user_type"]

    def validate(self, attrs):
        # Ensure user_type is 'individual'
        #if attrs.get("user_type") != "individual":
        #    raise serializers.ValidationError("Invalid user type for individual registration.")
        return attrs

    def create(self, validated_data):
        try:
            with transaction.atomic():
                # Retrieve user and data
                user = self.context['request'].user
                # Ensure user is marked as an employee and registration is complete
                user.user_type = 'individual'
                user.is_registration_complete = True
                user.save()
                return user
        except Exception as e:
            raise serializers.ValidationError(f"Registration failed: {str(e)}")


class AgentRegistrationSerializer(serializers.Serializer):
    agent_username = serializers.CharField(required=True, allow_null=False)
    agent_email = serializers.CharField(required=True, allow_null=False)

    def validate(self, attrs):
        existing_agent = CustomUser.objects.filter(email=attrs["agent_email"]).first()
        if existing_agent:
            raise serializers.ValidationError(f"Agent '{existing_agent.email}' is already taken")
        return attrs

    def create(self, validated_data):
        try:
            with transaction.atomic():
                agent_user = CustomUser.objects.create(
                    email=validated_data.get('agent_email'),
                    username=validated_data.get('agent_username'),
                    is_active=True,
                )
                # Retrieve user and data
                user = self.context['request'].user
                enterprise_profile = getattr(user, "enterprise_profile", None)
                organization = getattr(enterprise_profile, "organization", None)
                # Update or create the EnterpriseProfile
                EnterpriseProfile.objects.update_or_create(
                    user=agent_user,
                    defaults={
                        'organization': organization,
                    },
                )
                # Ensure user is marked as an employee and registration is complete
                agent_user.user_type = 'agent'
                agent_user.is_registration_complete = True
                agent_user.save()
                return agent_user
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise serializers.ValidationError(f"Registration failed: {str(e)}")