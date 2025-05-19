import os
import time
from django.apps import AppConfig
from django.conf import settings


def start_campaign_schedule_task():
    from .tasks import process_campaign_schedule_message
    # Check if lock exists
    if os.path.exists(settings.LOCK_FILE_CAMPAIGN):
        return
    # Create a new lock with the current timestamp
    try:
        with open(settings.LOCK_FILE_CAMPAIGN, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        return
    # Stopping if there is already instance of the task running
    #redis.StrictRedis.from_url(settings.CELERY_BROKER_URL).set('STOP_KAFKA_CONSUMER', 'true')
    #time.sleep(60) # Wait for a minute
    #redis.StrictRedis.from_url(settings.CELERY_BROKER_URL).set('STOP_KAFKA_CONSUMER', 'false')
    # Start Kafka consumer in Celery
    process_campaign_schedule_message.delay()

class ManageCampaignConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'manage_campaign'
    def ready(self):
        # Start the campaign tasks
        #start_campaign_schedule_task()
        pass
