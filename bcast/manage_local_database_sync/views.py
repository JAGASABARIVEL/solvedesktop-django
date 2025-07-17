from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated  # Optional for auth
from rest_framework.response import Response
from rest_framework import status
from django.db import connection
from .models import TableMapping
from .utils import get_dynamic_cursor

@api_view(['POST'])
# @permission_classes([IsAuthenticated])  # Enable if you're using token auth
@api_view(['POST'])
def sync_mapping(request):
    mappings = request.data.get("mappings", [])
    if not mappings:
        return Response({"error": "No mappings provided"}, status=status.HTTP_400_BAD_REQUEST)
    failed = []
    for entry in mappings:
        database_name = entry.get("database_name")
        table_name = entry.get("table_name")
        if not database_name or not table_name:
            return Response({"error": "Missing database_name or table_name in one of the entries"}, status=status.HTTP_400_BAD_REQUEST)
        # Check if mapping already exists
        if TableMapping.objects.filter(database_name=database_name, table_name=table_name).exists():
            failed.append({"database_name": database_name, "table_name": table_name, "error": "Mapping already exists"})
            continue
        TableMapping.objects.create(
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

@api_view(['POST'])
# @permission_classes([IsAuthenticated])  # Enable if you're using token auth
def sync_data(request):
    database_name = request.data.get("database")
    table_name = request.data.get("table_name")
    rows = request.data.get("rows", [])
    if not (database_name and table_name and rows):
        return Response({"error": "Missing database, table_name or rows"}, status=400)
    try:
        with get_dynamic_cursor(database_name) as cursor:
            for row in rows:
                columns = ', '.join(f'"{col}"' for col in row.keys())
                values = list(row.values())
                placeholders = ', '.join(['%s'] * len(values))
                sql = f'INSERT INTO "{table_name}" ({columns}) VALUES ({placeholders})'
                cursor.execute(sql, values)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
    return Response({"status": f"{len(rows)} rows inserted into {database_name}.{table_name}"})
