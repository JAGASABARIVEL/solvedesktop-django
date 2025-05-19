from datetime import datetime
from dateutil.relativedelta import relativedelta
from collections import defaultdict
from calendar import monthrange

from django.db.models import Q
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.timezone import make_aware, localtime, now

from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

import boto3
from botocore.exceptions import ClientError

from manage_subscriptions.models import Payment
from .models import FilePermission, File, FileStorageEvent, FileDownloadEvent, PaymentFiles
from .serializers import FilePermissionSerializer, FileSerializer, FolderSerializer, FileUploadSerializer, CostReportSerializer
from manage_users.permissions import EnterpriseIndividualUsers


from decimal import Decimal
from django.utils.timezone import now
from manage_files.models import FileStorageEvent, FileDownloadEvent
from manage_subscriptions.models import Payment
from django.db.models import Sum


def get_total_download_cost_until(user, target_date):
    """
    Calculates the total download cost for a user until the end of the selected month.
    """
    end_of_month = target_date.replace(day=1) + relativedelta(months=1)

    download_events = FileDownloadEvent.objects.filter(
        user=user,
        timestamp__lt=end_of_month
    )
    total_gb = download_events.aggregate(total=Sum('size_gb'))["total"] or 0.0
    return total_gb * settings.DOWNLOAD_COST_PER_GB


def check_usage_dues(user, app_name="manage_files", threshold=Decimal("100.00")):
    current_time = now()

    storage_cost = sum(e.get_total_cost_until(current_time)
                       for e in FileStorageEvent.objects.filter(user=user))
    download_cost = get_total_download_cost_until(user, current_time)
    total_cost = storage_cost + download_cost

    total_paid = Payment.objects.filter(
        user=user,
        transaction_type="app_usage",
        subscription__plan__app__app_name=app_name
    ).aggregate(total=Sum("amount"))["total"] or 0.0

    unpaid_due = total_cost - total_paid

    return {
        "is_blocked": unpaid_due > threshold,
        "due_amount": float(unpaid_due),
        "threshold": float(threshold),
        "block_reason": "usage_due" if unpaid_due > threshold else None
    }


class FilePermissionView(generics.CreateAPIView):
    """Allow file owners to grant or update permissions."""
    serializer_class = FilePermissionSerializer
    permission_classes = [EnterpriseIndividualUsers]

    def perform_create(self, serializer):
        file = serializer.validated_data["file"]
        user = serializer.validated_data["user"]
        can_read = serializer.validated_data.get("can_read", True)  # Default: Read allowed
        can_write = serializer.validated_data.get("can_write", False)  # Default: Write not allowed
        # Ensure the requester is the owner
        if file.owner != self.request.user:
            raise permissions.PermissionDenied("You do not have permission to share this file/folder.")
        # Check if permission already exists and update instead of duplicating
        permission, created = FilePermission.objects.update_or_create(
            file=file,
            user=user,
            defaults={"can_read": can_read, "can_write": can_write}
        )
        # If the file is a folder, apply permissions recursively
        if file.is_folder():
            self.apply_permissions_to_children(file, user, can_read, can_write)
        return Response({"message": "Permission granted successfully."}, status=status.HTTP_201_CREATED)

    def apply_permissions_to_children(self, parent_file, user, can_read, can_write):
        """Recursively apply permissions to all child files/folders."""
        children = File.objects.filter(parent=parent_file, is_deleted=False)
        for child in children:
            FilePermission.objects.update_or_create(
                file=child,
                user=user,
                defaults={"can_read": can_read, "can_write": can_write, "inherited": True}
            )
            # If the child is also a folder, apply to its children
            if child.is_folder():
                self.apply_permissions_to_children(child, user, can_read, can_write)


class FilePermissionListView(generics.ListAPIView):
    """Lists users with whom a file is shared along with their permissions."""
    permission_classes = [EnterpriseIndividualUsers]

    def get(self, request, file_id):
        file = get_object_or_404(File, id=file_id)

        # Ensure only the owner can view shared permissions
        if file.owner != request.user:
            return Response({"error": "You do not have permission to view this file's sharing details."}, status=status.HTTP_403_FORBIDDEN)

        # Retrieve all permissions for this file
        shared_users = FilePermission.objects.filter(file=file).select_related("user")

        # Format the response data
        response_data = [
            {
                "user": perm.user.id,
                "email": perm.user.email,
                "file":file_id,
                "can_read": perm.can_read,
                "can_write": perm.can_write,
            }
            for perm in shared_users
        ]

        return Response(response_data, status=status.HTTP_200_OK)


class FilePermissionUpdateView(generics.UpdateAPIView):
    """Update file/folder permissions (read/write) for a specific user."""
    serializer_class = FilePermissionSerializer
    permission_classes = [EnterpriseIndividualUsers]

    def patch(self, request, *args, **kwargs):
        file_id = request.data.get("file")
        user_id = request.data.get("user")
        can_read = request.data.get("can_read")
        can_write = request.data.get("can_write")

        if not file_id or not user_id:
            return Response({"error": "Both 'file' and 'user' fields are required."}, status=status.HTTP_400_BAD_REQUEST)

       # Ensure the requesting user is the owner of the file
        try:
            file = File.objects.get(id=file_id, owner=request.user)
        except File.DoesNotExist:
            return Response({"error": "You do not own this file or it does not exist."}, status=status.HTTP_403_FORBIDDEN)

        # Check if the permission exists
        permission = FilePermission.objects.filter(file=file, user_id=user_id).first()
        if not permission:
            return Response({"error": "Permission does not exist for the specified user and file."}, status=status.HTTP_404_NOT_FOUND)

        # Update read/write permissions if specified
        if can_read is not None:
            permission.can_read = can_read
        if can_write is not None:
            permission.can_write = can_write
        permission.save()

        # If it's a folder, apply the updated permissions to inherited children
        if file.is_folder():
            self.update_inherited_permissions(file, user_id, can_read, can_write)

        return Response({"message": "Permission updated successfully."}, status=status.HTTP_200_OK)

    def update_inherited_permissions(self, parent_file, user_id, can_read, can_write):
        """Recursively update inherited permissions for all child files/folders."""
        children = File.objects.filter(parent=parent_file, is_deleted=False)
        for child in children:
            permission = FilePermission.objects.filter(file=child, user_id=user_id, inherited=True).first()
            if permission:
                if can_read is not None:
                    permission.can_read = can_read
                if can_write is not None:
                    permission.can_write = can_write
                permission.save()
                
                # Recursively update child folders
                if child.is_folder():
                    self.update_inherited_permissions(child, user_id, can_read, can_write)

class FilePermissionDeleteView(generics.GenericAPIView):
    serializer_class = FilePermissionSerializer
    permission_classes = [EnterpriseIndividualUsers]
    def delete(self, request, *args, **kwargs):
        """Revoke permission for a specific user and file, and propagate if it's a folder."""
        file_id = request.data.get("file")
        user_id = request.data.get("user")

        if not file_id or not user_id:
            return Response({"error": "Both 'file' and 'user' fields are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure the requesting user is the owner of the file
        try:
            file = File.objects.get(id=file_id, owner=request.user)
        except File.DoesNotExist:
            return Response({"error": "You do not own this file or it does not exist."}, status=status.HTTP_403_FORBIDDEN)

        # Get the file permission entry
        try:
            permission = FilePermission.objects.get(file=file, user_id=user_id)
        except FilePermission.DoesNotExist:
            return Response({"error": "Permission does not exist for the specified user and file."}, status=status.HTTP_404_NOT_FOUND)

        # Delete the permission for the file itself
        permission.delete()

        # If it's a folder, revoke inherited permissions for all child files/folders
        if file.is_folder():
            children = File.objects.filter(parent=file, is_deleted=False)  # Get all children
            FilePermission.objects.filter(file__in=children, user_id=user_id, inherited=True).delete()

        return Response({"message": "Permission revoked successfully."}, status=status.HTTP_204_NO_CONTENT)


#s3 = boto3.client('s3', aws_access_key_id=settings.AWS_ACCESS_KEY_ID, aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
from botocore.client import Config
s3 = boto3.client(
    's3',
    endpoint_url=settings.B2_ENDPOINT_URL,
    aws_access_key_id=settings.B2_ACCESS_KEY_ID,
    aws_secret_access_key=settings.B2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
)

class FolderCreateView(generics.CreateAPIView):
    serializer_class = FolderSerializer
    permission_classes = [EnterpriseIndividualUsers]
    def perform_create(self, serializer):
        user = self.request.user
        folder_name = serializer.validated_data["name"]
        parent = serializer.validated_data.get("parent", None)
        # Step 1: Ensure home folder exists for user if parent is None
        if parent is None:
            uname = user.email.split('@')[0]
            home_folder, created = File.objects.get_or_create(
                name=uname,
                owner=user,
                parent=None,
                defaults={
                    "s3_key": f"{uname}/",
                    "size_gb": 0,
                    "is_deleted": False
                }
            )
            # Ensure it's active even if it was soft-deleted before
            if home_folder.is_deleted:
                home_folder.is_deleted = False
                home_folder.save()
            if created:
                # Create the actual "folder" in S3
                s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=home_folder.s3_key)
            parent = home_folder
        # Step 2: Check permission if not the owner
        if parent and parent.owner != user:
            permission = FilePermission.objects.filter(file=parent, user=user, can_write=True).first()
            if not permission:
                raise permissions.PermissionDenied("You do not have write permission to create a folder here.")
        # Step 3: Build S3 path and check for duplicates
        parent_path = parent.s3_key
        s3_key = f"{parent_path}{folder_name}/"
        if File.objects.filter(parent=parent, name=folder_name, owner=user, is_deleted=False).exists():
            raise serializers.ValidationError("A folder with this name already exists.")
        # Step 4: Actually create the folder
        s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key)
        serializer.save(owner=user if parent.owner == user else parent.owner, s3_key=s3_key, parent=parent, size_gb=0)


class FileUploadView(generics.CreateAPIView):
    serializer_class = FileUploadSerializer
    permission_classes = [EnterpriseIndividualUsers]

    def perform_create(self, serializer):
        user = self.request.user
        uploaded_file = serializer.validated_data["file"]
        parent = serializer.validated_data.get("parent", None)
        # Step 1: Ensure home folder exists if parent is None
        if parent is None:
            uname = user.email.split('@')[0]
            home_folder, created = File.objects.get_or_create(
                name=uname,
                owner=user,
                parent=None,
                defaults={
                    "is_folder": True,
                    "s3_key": f"{uname}/",
                    "size_gb": 0
                }
            )
            if created:
                s3.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=home_folder.s3_key)
            parent = home_folder
        # Step 2: Check permission if parent is not owned by user
        if parent and parent.owner != user:
            permission = FilePermission.objects.filter(file=parent, user=user, can_write=True).first()
            if not permission:
                raise permissions.PermissionDenied("You do not have write permission to upload a file here.")
        # Step 3: Determine S3 key
        parent_path = parent.s3_key
        s3_key = f"{parent_path}{uploaded_file.name}"
        # Step 4: Prevent duplicate file names at the same level
        if File.objects.filter(parent=parent, name=uploaded_file.name, owner=user, is_deleted=False).exists():
            raise serializers.ValidationError("A file with this name already exists.")
        # Step 5: Upload file to S3
        s3.upload_fileobj(uploaded_file, settings.AWS_STORAGE_BUCKET_NAME, s3_key)
        # Step 6: Save instance
        serializer.save(
            owner=user if parent.owner == user else parent.owner,
            s3_key=s3_key,
            parent=parent
        )



class OrganizationQuerysetMixin:
    def get_queryset(self):
        if not self.request.user.user_type in {"owner", "employee", "agent"}:
            return super().get_queryset()
        user_org = self.request.user.enterprise_profile.organization
        if user_org:
            # Correct: Access all related enterprise profiles from the organization
            org_user_ids = user_org.enterprise_profiles.values_list('user_id', flat=True)
            ret = super().get_queryset().filter(owner_id__in=org_user_ids, is_deleted=False)
            return ret
        return File.objects.none()


class FileListView(generics.ListAPIView):
    serializer_class = FileSerializer
    permission_classes = [EnterpriseIndividualUsers]

    def get_queryset(self):
        user = self.request.user
        parent_id = self.request.query_params.get("parent", None)
        is_folder = True if self.request.query_params.get("isFolder", None) == "true" else False

        # Get all files/folders where the user has explicit permissions
        shared_files = File.objects.filter(permissions__user=user, permissions__can_read=True, is_deleted=False).values_list("id", flat=True)
        # Include all files inside shared folders
        inherited_files = File.objects.filter(parent_id__in=shared_files, is_deleted=False).values_list("id", flat=True)
        queryset = File.objects.filter(
            Q(owner=user) |  # Owner's files
            Q(id__in=shared_files) |  # Directly shared files/folders
            Q(id__in=inherited_files)  # Files inside shared folders
        ).select_related("owner", "parent")
        # This is when user clicks directly on the files from shared folder tree in left panel
        if parent_id and not is_folder:
            return queryset.filter(id=parent_id, is_deleted=False)
        # This is for normal query from file explorer window
        if parent_id:
            return queryset.filter(parent_id=parent_id, is_deleted=False)
        return queryset.filter(parent__isnull=True, is_deleted=False)  # Root-level files/folders
        
            

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        # Get shared files where the user has granted permissions to others (mine)
        mine_shared_ids = set(FilePermission.objects.filter(file__owner=request.user).values_list("file_id", flat=True))
        # Get shared files where the user has received access from others (others)
        others_shared_ids = set(FilePermission.objects.filter(user=request.user).values_list("file_id", flat=True))

        # Convert queryset to list with additional field
        response_data = [
            {
                "id": file.id,
                "name": file.name,
                "created_at": localtime(file.created_at).isoformat(),
                "parent": file.parent_id,
                "is_folder": file.is_folder(),
                "s3_key": file.s3_key,
                "is_shared": file.id in mine_shared_ids or file.id in others_shared_ids,
                "owner": file.owner.id
            }
            for file in queryset
        ]
        return Response(response_data)


class FileRetrieveView(OrganizationQuerysetMixin, generics.RetrieveAPIView):
    serializer_class = FileSerializer
    permission_classes = [EnterpriseIndividualUsers]
    queryset = File.objects.all()



from django.db.models import Sum
from rest_framework import generics


class OrganizedFileListView(generics.ListAPIView):
    serializer_class = FileSerializer
    permission_classes = [EnterpriseIndividualUsers]
    queryset = File.objects.all()

    def get(self, request):
        user = request.user

        # Home files owned by user
        home_queryset = File.objects.filter(owner=user, is_deleted=False)

        # Total size in GB of user's own files
        total_capacity_gb = home_queryset.filter(size_gb__isnull=False).aggregate(
            total=Sum("size_gb")
        )["total"] or 0.0

        # --- SHARED BY ME ---
        mine_shared_ids = FilePermission.objects.filter(file__owner=user).values_list("file_id", flat=True).distinct()
        mine_shared_queryset = File.objects.filter(id__in=mine_shared_ids, is_deleted=False)

        # --- SHARED TO ME ---
        others_shared_ids = FilePermission.objects.filter(user=user).values_list("file_id", flat=True).distinct()
        others_shared_queryset = File.objects.filter(id__in=others_shared_ids, is_deleted=False)

        def build_tree(parent_id, file_list, shared_ids=None, is_shared=False):
            shared_ids = shared_ids or set()
            nodes = []
        
            for file in file_list:
                if (file.parent_id == parent_id):
                    node = {
                        "id": file.id,
                        "name": file.name,
                        "created_at": file.created_at,
                        "parent": file.parent_id,
                        "is_folder": file.is_folder(),
                        "s3_key": file.s3_key,
                        "is_shared": is_shared or file.id in shared_ids,
                        "children": build_tree(file.id, file_list, shared_ids, is_shared),
                        "owner": file.owner.id
                    }
                    nodes.append(node)
            return nodes

        def build_partial_tree_from_shared_files(shared_queryset, shared_ids):
            """
            For files (not folders) that are shared individually, construct tree including only the path to them.
            """
            all_required_ids = set()
            file_map = {f.id: f for f in File.objects.filter(is_deleted=False)}
            for file in shared_queryset:
                current = file
                while current:
                    all_required_ids.add(current.id)
                    current = file_map.get(current.parent_id)

            filtered_queryset = File.objects.filter(id__in=all_required_ids, is_deleted=False)

            def recurse(parent_id):
                nodes = []
                children = filtered_queryset.filter(parent_id=parent_id)
                for file in children:
                    node = {
                        "id": file.id,
                        "name": file.name,
                        "created_at": file.created_at,
                        "parent": file.parent_id,
                        "is_folder": file.is_folder(),
                        "s3_key": file.s3_key,
                        "is_shared": file.id in shared_ids,
                        "children": recurse(file.id),
                        "owner": file.owner.id
                    }
                    nodes.append(node)
                return nodes

            return recurse(None)

        # --- Build home tree (owned by user) ---
        home_directory = build_tree(None, home_queryset)

        # --- Build mine shared tree (shared by user) ---
        mine_shared_folders = [f for f in mine_shared_queryset if f.is_folder()]
        mine_shared_files = [f for f in mine_shared_queryset if not f.is_folder()]
        mine_shared_tree = build_tree(None, mine_shared_folders, mine_shared_ids, is_shared=True)

        if mine_shared_files:
            mine_partial_tree = build_partial_tree_from_shared_files(mine_shared_files, mine_shared_ids)
            mine_shared_tree.extend(mine_partial_tree)

        # --- Build others shared tree (shared to user) ---
        others_shared_folders = [f for f in others_shared_queryset if f.is_folder()]
        others_shared_files = [f for f in others_shared_queryset if not f.is_folder()]
        others_shared_tree = build_tree(None, others_shared_folders, others_shared_ids, is_shared=True)

        if others_shared_files:
            others_partial_tree = build_partial_tree_from_shared_files(others_shared_files, others_shared_ids)
            others_shared_tree.extend(others_partial_tree)

        return Response({
            "home": home_directory,
            "shared_folders": {
                "mine": mine_shared_tree,
                "others": others_shared_tree
            },
            "total_capacity_gb": total_capacity_gb
        })




class FileDeleteView(generics.DestroyAPIView):
    permission_classes = [EnterpriseIndividualUsers]

    def delete(self, request, *args, **kwargs):
        file_id = request.data.get("file")
        if not file_id:
            return Response({"error": "File ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            file = File.objects.get(id=file_id, is_deleted=False)
        except File.DoesNotExist:
            return Response({"error": "File not found."}, status=status.HTTP_404_NOT_FOUND)

        # Permission check
        if file.owner != request.user:
            has_write_permission = FilePermission.objects.filter(
                file=file, user=request.user, can_write=True
            ).exists()
            if not has_write_permission:
                return Response({"error": "You don't have permission to delete this file."},
                                status=status.HTTP_403_FORBIDDEN)

        # Gather all descendants recursively
        def collect_descendants(f):
            descendants = []
            children = File.objects.filter(parent=f, is_deleted=False)
            for child in children:
                descendants.append(child)
                descendants.extend(collect_descendants(child))
            return descendants

        all_to_delete = [file] + collect_descendants(file)

        for f in all_to_delete:
            # Delete from S3
            self.delete_s3_object(f.s3_key)

            # Mark end_time for active storage events (files only)
            if not f.is_folder():
                FileStorageEvent.objects.filter(file_id=f.id, end_time__isnull=True).update(end_time=now())

        # Soft delete in DB
        File.objects.filter(id__in=[f.id for f in all_to_delete]).update(is_deleted=True)

        return Response({"message": "File/folder and contents marked as deleted."},
                        status=status.HTTP_204_NO_CONTENT)

    def delete_s3_object(self, s3_key):
        try:
            response = s3.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key)
        except Exception as e:
            print("S3 Deletion Error:", e)


class FileDownloadView(APIView):
    permission_classes = [EnterpriseIndividualUsers]

    def get(self, request, file_id):
        try:
            file = File.objects.get(id=file_id)
        except File.DoesNotExist:
            return JsonResponse({"error": "File not found."}, status=404)

        if file.owner != request.user:
            has_read_permission = FilePermission.objects.filter(
                file=file, user=request.user, can_read=True
            ).exists()
            if not has_read_permission:
                return JsonResponse({"error": "You don't have permission to download this file."}, status=403)

        if file.is_folder():
            return JsonResponse({"error": "Cannot download a folder."}, status=400)

        try:
            # Get object size from S3
            s3_object = s3.head_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=file.s3_key
            )
            file_size = s3_object.get('ContentLength', 0)

            signed_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": file.s3_key},
                ExpiresIn=3600
            )

            # Log the download
            FileDownloadEvent.objects.create(
                user=request.user,
                file_id=file,
                file_name=file.name,
                size_gb=file_size / (1024 ** 3)  # Convert file size from bytes to GB
            )

            return JsonResponse({"download_url": signed_url})
        except ClientError as e:
            return JsonResponse({"error": "Failed to generate download URL."}, status=500)

def format_cost_inr(value):
    if value < 0.01:
        return f"{value:.5f}"  # Show 5 decimal places for tiny costs
    return f"{value:.2f}"     # Round to 2 decimal places otherwise


class CostReportView(APIView):
    permission_classes = [EnterpriseIndividualUsers]

    def get(self, request):
        user = request.user
        usage_check = check_usage_dues(request.user, threshold=settings.FILE_STORAGE_DUE_THRESHOLD)
        if usage_check["is_blocked"]:
            return Response({"error": "Due is pending. Please clear them to access the application"}, status=status.HTTP_402_PAYMENT_REQUIRED)

        # Get month and year from query parameters
        try:
            month = int(request.query_params.get("month", now().month))
            year = int(request.query_params.get("year", now().year))

            current_month = now().replace(year=year, month=month, day=1)
            selected_month_start = now().replace(year=year, month=month, day=1)
            selected_month_end = selected_month_start.replace(day=monthrange(year, month)[1])

            start_of_month = make_aware(datetime(year, month, 1))
            end_of_month = make_aware(datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1))
        except ValueError:
            return Response({"error": "Invalid month or year"}, status=status.HTTP_400_BAD_REQUEST)

        # Storage Events
        storage_events = FileStorageEvent.objects.filter(
            user=user,
            start_time__gte=start_of_month,
            start_time__lt=end_of_month
        )
        storage_cost_by_file = defaultdict(float)
        total_storage_cost = 0.0
        for event in storage_events:
            if event.start_time and event.start_time > selected_month_end:
                continue  # Skip files created after selected month
            cost = event.get_cost_for_month()
            if cost < 0:
                continue
            storage_cost_by_file[event.file_id.id] = cost
            total_storage_cost += cost
        total_storage_cost = format_cost_inr(total_storage_cost)

        # Download Events
        download_events = FileDownloadEvent.objects.filter(
            user=user,
            timestamp__year=year,
            timestamp__month=month
        )
        download_cost_by_file = defaultdict(float)
        total_download_cost = 0.0

        for event in download_events:
            cost = event.get_cost()
            if cost < 0:
                continue
            download_cost_by_file[event.file_id.id] = cost
            total_download_cost += cost
        total_download_cost = format_cost_inr(total_download_cost)

        # Generic Payment model: fetch previous payments for manage_files
        previous_payments = Payment.objects.filter(
            subscription__plan__app__app_name="manage_files",
            user=user,
            transaction_type="app_usage",
            timestamp__lt=end_of_month
        )
        total_paid = previous_payments.aggregate(total=Sum("amount"))["total"] or 0.0

        until_storage_events = FileStorageEvent.objects.filter(user=user)
        until_total_storage_cost = sum(event.get_total_cost_until(current_month) for event in until_storage_events)
        until_download_cost = get_total_download_cost_until(user, current_month)

        total_cost = until_total_storage_cost + until_download_cost
        balance = total_paid - total_cost

        if balance >= 0:
            total_due = 0.0
            excess_credit = balance
        else:
            total_due = abs(balance)
            excess_credit = 0.0

        breakdown = []
        for file in storage_events:
            breakdown.append({
                "file_id": file.file_id.id,
                "file_name": file.file_name,
                "file_size": file.size_gb,
                "storage_cost": storage_cost_by_file.get(file.file_id.id, 0.0),
                "download_cost": download_cost_by_file.get(file.file_id.id, 0.0),
            })

        data = {
            "total_storage_cost": total_storage_cost,
            "total_download_cost": total_download_cost,
            "file_breakdown": breakdown,
            "total_due": total_due,
            "excess_credit": excess_credit
        }
        return Response(CostReportSerializer(data).data)
