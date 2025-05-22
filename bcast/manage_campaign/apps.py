import os
import time
from django.apps import AppConfig
from django.conf import settings


class ManageCampaignConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'manage_campaign'
