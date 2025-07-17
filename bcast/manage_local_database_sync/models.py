from django.db import models

class TableMapping(models.Model):
    database_name = models.CharField(max_length=255)
    table_name = models.CharField(max_length=255)
    primary_keys = models.JSONField(default=list)
    foreign_keys = models.JSONField(default=list)
    entity_type = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        unique_together = ('database_name', 'table_name')
