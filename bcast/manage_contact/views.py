from django.db import transaction

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView

import pyexcel

from .models import Contact, ContactCustomField, ContactCustomFieldValue, ContactGroup, GroupMember
from .serializers import ContactSerializer, ContactCustomFieldSerializer, ContactGroupSerializer, GroupMemberSerializer
from manage_users.permissions import EnterpriserUsers


# Base Mixin to Filter by Organization
class OrganizationQuerysetMixin:
    def get_queryset(self):
        user_org = self.request.user.enterprise_profile.organization
        return super().get_queryset().filter(organization=user_org)


class ContactCustomFieldListCreateView(OrganizationQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = ContactCustomFieldSerializer
    permission_classes = [EnterpriserUsers]
    queryset = ContactCustomField.objects.all()

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.enterprise_profile.organization)


# views.py
class ContactCustomFieldRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [EnterpriserUsers]
    serializer_class = ContactCustomFieldSerializer
    queryset = ContactCustomField.objects.all()

    def perform_destroy(self, instance):
        # delete related values before deleting field
        ContactCustomFieldValue.objects.filter(custom_field=instance).delete()
        instance.delete()


# Contact Views
class ContactListCreateView(OrganizationQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = ContactSerializer
    permission_classes = [EnterpriserUsers]
    queryset = Contact.objects.all()


class ContactDetailView(OrganizationQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ContactSerializer
    permission_classes = [EnterpriserUsers]
    queryset = Contact.objects.all()


class BulkDeleteContactView(generics.DestroyAPIView):
    permission_classes = [EnterpriserUsers]

    def delete(self, request, *args, **kwargs):
        contact_ids = request.data.get('contact_ids', [])
        user_org = request.user.enterprise_profile.organization

        # Delete only contacts from the user's organization
        deleted_count, _ = Contact.objects.filter(id__in=contact_ids, organization=user_org).delete()
        return Response({"deleted": deleted_count}, status=status.HTTP_204_NO_CONTENT)


class ContactImportView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, *args, **kwargs):
        user = request.user

        # Ensure the user has an organization
        organization = getattr(user.enterprise_profile, 'organization', None)
        if not organization:
            return Response({'error': 'Organization is required'}, status=status.HTTP_400_BAD_REQUEST)

        if 'file' not in request.FILES:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        file = request.FILES['file']

        try:
            # Read the uploaded Excel file
            sheet = pyexcel.get_sheet(file_type='xlsx', file_content=file.read())

            # Validate required columns
            required_columns = ['name', 'description', 'phone', 'address', 'category']
            sheet_columns = sheet.row_at(0)  # First row is the header

            if not all(col in sheet_columns for col in required_columns):
                return Response({'error': 'Invalid file format. Required columns: name, description, phone, address, category'},
                                status=status.HTTP_400_BAD_REQUEST)

            # Process data and store it
            imported_count = 0
            errors = []
            with transaction.atomic():
                for row in sheet.rows():
                    if row == sheet_columns:  # Skip header row
                        continue

                    contact_data = dict(zip(sheet_columns, row))

                    # Check if contact already exists
                    if Contact.objects.filter(phone=contact_data['phone'], organization=organization).exists():
                        continue

                    # Validate and save the contact
                    serializer = ContactSerializer(data=contact_data, context={'request': request})

                    if serializer.is_valid():
                        serializer.save(organization=organization, created_by=user)
                        imported_count += 1
                    else:
                        errors.append({'phone': contact_data['phone'], 'errors': serializer.errors})

            return Response({
                'message': 'Contacts imported successfully',
                'imported_count': imported_count,
                'errors': errors
            }, status=status.HTTP_200_OK)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ContactImportView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, *args, **kwargs):
        user = request.user
        organization = getattr(user.enterprise_profile, 'organization', None)

        if not organization:
            return Response({'error': 'Organization is required'}, status=status.HTTP_400_BAD_REQUEST)

        if 'file' not in request.FILES:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        file = request.FILES['file']

        try:
            # Read Excel sheet
            sheet = pyexcel.get_sheet(file_type='xlsx', file_content=file.read())

            # Header row
            sheet_columns = sheet.row_at(0)
            required_columns = ['name', 'description', 'phone', 'address', 'category']

            if not all(col in sheet_columns for col in required_columns):
                return Response(
                    {'error': f'Invalid format. Required columns: {", ".join(required_columns)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            imported_count = 0
            updated_count = 0
            errors = []

            with transaction.atomic():
                for row in sheet.rows():
                    if row == sheet_columns:  # Skip header
                        continue

                    contact_data = dict(zip(sheet_columns, row))

                    # Separate standard and custom fields
                    base_data = {k: v for k, v in contact_data.items() if k in required_columns}
                    custom_fields = {k: v for k, v in contact_data.items() if k not in required_columns}

                    phone = contact_data.get('phone')
                    if not phone:
                        errors.append({'row': contact_data, 'errors': 'Missing phone'})
                        continue

                    contact_qs = Contact.objects.filter(phone=phone, organization=organization)

                    if contact_qs.exists():
                        # PATCH: Update existing contact
                        contact = contact_qs.first()
                        serializer = ContactSerializer(
                            contact,
                            data=base_data,
                            partial=True,
                            context={'request': request, 'custom_fields': custom_fields}
                        )
                        if serializer.is_valid():
                            serializer.save()
                            updated_count += 1
                        else:
                            errors.append({'phone': phone, 'errors': serializer.errors})
                    else:
                        # CREATE new contact
                        serializer = ContactSerializer(
                            data=base_data,
                            context={'request': request, 'custom_fields': custom_fields}
                        )
                        if serializer.is_valid():
                            serializer.save(organization=organization, created_by=user)
                            imported_count += 1
                        else:
                            errors.append({'phone': phone, 'errors': serializer.errors})

            return Response({
                'message': 'Contacts processed successfully',
                'imported_count': imported_count,
                'updated_count': updated_count,
                'errors': errors
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Contact Group Views
class ContactGroupListCreateView(OrganizationQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = ContactGroupSerializer
    permission_classes = [EnterpriserUsers]
    queryset = ContactGroup.objects.all()


class ContactGroupDetailView(OrganizationQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ContactGroupSerializer
    permission_classes = [EnterpriserUsers]
    queryset = ContactGroup.objects.all()


class BulkDeleteGroupView(generics.DestroyAPIView):
    permission_classes = [EnterpriserUsers]

    def delete(self, request, *args, **kwargs):
        group_ids = request.data.get('group_ids', [])
        user_org = request.user.enterprise_profile.organization

        # Delete only groups from the user's organization
        deleted_count, _ = ContactGroup.objects.filter(id__in=group_ids, organization=user_org).delete()
        return Response({"deleted": deleted_count}, status=status.HTTP_204_NO_CONTENT)


# Group Member Views
class GroupMemberListCreateView(OrganizationQuerysetMixin, generics.ListCreateAPIView):
    serializer_class = GroupMemberSerializer
    permission_classes = [EnterpriserUsers]
    queryset = GroupMember.objects.all()


class GroupMemberDetailView(OrganizationQuerysetMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = GroupMemberSerializer
    permission_classes = [EnterpriserUsers]
    queryset = GroupMember.objects.all()


class BulkDeleteGroupMemberView(generics.DestroyAPIView):
    permission_classes = [EnterpriserUsers]

    def delete(self, request, *args, **kwargs):
        member_ids = request.data.get('member_ids', [])
        user_org = request.user.enterprise_profile.organization

        # Delete only group members belonging to the user's organization
        deleted_count, _ = GroupMember.objects.filter(id__in=member_ids, group__organization=user_org).delete()
        return Response({"deleted": deleted_count}, status=status.HTTP_204_NO_CONTENT)
