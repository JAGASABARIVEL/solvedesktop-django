from django.db import models

class TableMapping(models.Model):
    table_name = models.CharField(max_length=255, unique=True)
    primary_keys = models.JSONField(default=list)
    foreign_keys = models.JSONField(default=list)
    entity_type = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
