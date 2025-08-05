from django.db import models
from django.conf import settings

# Create your models here.


class Organization(models.Model):
    ALLOCATION_ALGO_CHOICES = (
        ('rr', 'RoundRobin'),
        ('bw', 'BandWidth'),
    )
    name = models.TextField(unique=True)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="owned_org")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    auto_allocation_enabled = models.BooleanField(default=False)
    auto_allocation_algorithm = models.TextField(choices=ALLOCATION_ALGO_CHOICES, default='rr')

