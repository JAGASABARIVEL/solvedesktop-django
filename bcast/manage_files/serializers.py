from rest_framework import serializers
from .models import FilePermission

from rest_framework import serializers
from .models import File, FilePermission, FileStorageEvent


class FolderSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = ["id", "name", "parent"]
    
    def validate(self, attrs):
        """Ensure folder name doesn't contain invalid characters."""
        if "/" in attrs["name"]:
            raise serializers.ValidationError("Folder name cannot contain '/'")
        return attrs


class FileUploadSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)  # For file upload

    class Meta:
        model = File
        fields = ["id", "name", "file", "parent"]

    def create(self, validated_data):
        uploaded_file = self.context["request"].FILES["file"]
        file_size = uploaded_file.size
        user = self.context["request"].user
        # Calculate size in GB for storage cost tracking
        size_in_gb = file_size / (1024 ** 3)  # Convert size from bytes to GB
        validated_data.pop("file")
        validated_data["size_gb"] = size_in_gb
        file_instance = super().create(validated_data)
        # Create a FileStorageEvent to track the file upload
        FileStorageEvent.objects.create(
            user=user,  # The user uploading the file
            file_id=file_instance,  # The file being uploaded
            file_name=file_instance.name,
            size_gb=size_in_gb  # The size of the file in GB
        )
        return file_instance

class FileSerializer(serializers.ModelSerializer):
    is_folder = serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = ["id", "name", "s3_key", "is_folder", "parent", "created_at", "owner"]

    def get_is_folder(self, obj):
        return obj.is_folder()

from django.contrib.auth import get_user_model
User = get_user_model()  # Retrieves the actual user model

class FilePermissionSerializer(serializers.ModelSerializer):
    file = serializers.PrimaryKeyRelatedField(queryset=File.objects.filter(is_deleted=False))
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())

    class Meta:
        model = FilePermission
        fields = ["id", "file", "user", "can_read", "can_write"]

    def validate(self, attrs):
        """Ensure only the owner can grant permissions."""
        file = attrs["file"]
        request_user = self.context["request"].user

        if file.owner != request_user:
            raise serializers.ValidationError("You are not the owner of this file.")

        return attrs

    def create(self, validated_data):
        """Create permission and propagate it to children if it's a folder."""
        permission = super().create(validated_data)

        # If the file is a folder, apply permissions to children
        if permission.file.is_folder:
            permission.apply_to_children()

        return permission


class FileCostBreakdownSerializer(serializers.Serializer):
    file_id = serializers.IntegerField()
    file_name = serializers.CharField()
    file_size = serializers.FloatField()
    storage_cost = serializers.FloatField()
    download_cost = serializers.FloatField()


class CostReportSerializer(serializers.Serializer):
    total_storage_cost = serializers.FloatField()
    total_download_cost = serializers.FloatField()
    total_due = serializers.FloatField(allow_null=True)
    excess_credit = serializers.FloatField(allow_null=True)
    file_breakdown = FileCostBreakdownSerializer(many=True)
