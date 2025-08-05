from django.db import models
from django.conf import settings

class TableMapping(models.Model):
    organization = models.ForeignKey(settings.ORG_MODEL, on_delete=models.CASCADE, related_name='db_mapping')
    database_name = models.CharField(max_length=128)
    table_name = models.CharField(max_length=128)
    primary_keys = models.JSONField(default=list)
    foreign_keys = models.JSONField(default=list)
    entity_type = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("organization", "database_name", "table_name")

