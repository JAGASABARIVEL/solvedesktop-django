from django.core.management.base import BaseCommand
from django.conf import settings
from manage_conversation.tasks import consume_kafka_messages
from manage_campaign.tasks import process_campaign_schedule_message

TOPIC = "whatsapp"
GRP_ID = "whatsapp-grp"
# TODO: Create the lock file in /tmp in production system.
LOCK_EXPIRY = 60 * 5  # 5 minutes expiry time


def read_config():
  # reads the client configuration from client.properties
  # and returns it as a key-value map
  config = {}
  with open(settings.KAFKA_CONFIG) as fh:
    for line in fh:
      line = line.strip()
      if len(line) != 0 and line[0] != "#":
        parameter, value = line.strip().split('=', 1)
        config[parameter] = value.strip()
  return config

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        consume_kafka_messages.apply_async(
            args=[TOPIC, GRP_ID, read_config()],
            queue="kafka_consumer_queue"
        )
        process_campaign_schedule_message.apply_async(
            queue="schedule_monitor_queue"
        )
