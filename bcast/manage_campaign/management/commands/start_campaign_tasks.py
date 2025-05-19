from django.core.management.base import BaseCommand
from manage_campaign.tasks import process_campaign_schedule_message

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        process_campaign_schedule_message.apply_async(
            queue="schedule_monitor_queue"
        )
