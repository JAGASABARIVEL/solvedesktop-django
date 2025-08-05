from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated  # Optional for auth
from rest_framework.response import Response
from rest_framework import status
from manage_users.permissions import EnterpriserUsers
from django.db import connection
from .models import TableMapping
from .utils import get_dynamic_cursor


@api_view(['POST'])
@permission_classes([])  # Add auth if needed
def sync_mapping(request):
    user = request.user
    enterprise_profile = getattr(user, "enterprise_profile", None)
    organization = getattr(enterprise_profile, "organization", None)
    if not organization:
        #return Response({"error": "User not linked to any organization"}, status=400)
        pass
    mappings = request.data.get("mappings", [])
    if not mappings:
        return Response({"error": "No mappings provided"}, status=status.HTTP_400_BAD_REQUEST)
    failed = []
    for entry in mappings:
        database_name = entry.get("database_name")
        table_name = entry.get("table_name")
        if not database_name or not table_name:
            return Response({"error": "Missing database_name or table_name"}, status=status.HTTP_400_BAD_REQUEST)
        if TableMapping.objects.filter(
            organization=organization,
            database_name=database_name,
            table_name=table_name
        ).exists():
            failed.append({
                "database_name": database_name,
                "table_name": table_name,
                "error": "Mapping already exists"
            })
            continue
        TableMapping.objects.create(
            #organization=organization,
            organization_id=5, #TODO: make thius dynamic
            database_name=database_name,
            table_name=table_name,
            primary_keys=entry.get("primary_keys", []),
            foreign_keys=entry.get("foreign_keys", []),
            entity_type=entry.get("entity_type", "")
        )
    if failed:
        return Response({
            "status": "Some mappings were rejected due to duplication",
            "rejected": failed
        }, status=status.HTTP_409_CONFLICT)
    return Response({"status": "All mappings created successfully"}, status=status.HTTP_201_CREATED)


from django.db import connections
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import re

@api_view(['POST'])
@permission_classes([])  # Enable if you're using token auth
@csrf_exempt
def sync_data(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST method is allowed"}, status=405)
    data = json.loads(request.body)
    table_name = data.get("table_name")
    records = data.get("records", [])
    if not table_name or not records:
        return JsonResponse({"error": "Missing table_name or records"}, status=400)
    if not re.match(r'^[a-zA-Z0-9_]+$', table_name):
        return JsonResponse({"error": "Invalid table name"}, status=400)
    # Get column definitions from the first record
    first_record = records[0]
    column_defs = ", ".join([f"{col} TEXT" for col in first_record.keys()])  # You can adjust type mapping here
    create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id SERIAL PRIMARY KEY,
            {column_defs}
        );
    """
    with connection.cursor() as cursor:
        try:
            # Create table if it doesn't exist
            cursor.execute(create_table_sql)
            # Insert records
            columns = list(first_record.keys())
            insert_sql = f"""
                INSERT INTO {table_name} ({','.join(columns)})
                VALUES ({','.join(['%s'] * len(columns))})
            """
            for record in records:
                values = [str(record[col]) for col in columns]
                cursor.execute(insert_sql, values)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"status": "success", "rows_inserted": len(records)})

