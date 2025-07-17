from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated  # Optional for auth
from rest_framework.response import Response
from django.db import connection
from .models import TableMapping

@api_view(['POST'])
# @permission_classes([IsAuthenticated])  # Enable if you're using token auth
def sync_mapping(request):
    mappings = request.data.get("mappings", [])
    for entry in mappings:
        TableMapping.objects.update_or_create(
            table_name=entry["table_name"],
            defaults={
                "primary_keys": entry.get("primary_keys", []),
                "foreign_keys": entry.get("foreign_keys", []),
                "entity_type": entry.get("entity_type", "")
            }
        )
    return Response({"status": "Mappings synced successfully"})

@api_view(['POST'])
# @permission_classes([IsAuthenticated])  # Enable if you're using token auth
def sync_data(request):
    table_name = request.data.get("table_name")
    rows = request.data.get("rows", [])

    if not table_name or not rows:
        return Response({"error": "Missing table_name or rows"}, status=400)

    with connection.cursor() as cursor:
        for row in rows:
            columns = ', '.join(f'"{col}"' for col in row.keys())
            values = list(row.values())
            placeholders = ', '.join(['%s'] * len(values))
            sql = f'INSERT INTO "{table_name}" ({columns}) VALUES ({placeholders})'
            cursor.execute(sql, values)

    return Response({"status": f"{len(rows)} rows inserted into {table_name}"})
