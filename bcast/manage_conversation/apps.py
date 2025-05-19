import os
import time
from django.apps import AppConfig
from django.conf import settings
import redis

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

def start_kafka_consumer_task():
    from .tasks import consume_kafka_messages
    # Check if lock exists
    if os.path.exists(settings.LOCK_FILE):
        return
    # Create a new lock with the current timestamp
    try:
        with open(settings.LOCK_FILE, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        return
    # Stopping if there is already instance of the task running
    #redis.StrictRedis.from_url(settings.CELERY_BROKER_URL).set('STOP_KAFKA_CONSUMER', 'true')
    #time.sleep(60) # Wait for a minute
    #redis.StrictRedis.from_url(settings.CELERY_BROKER_URL).set('STOP_KAFKA_CONSUMER', 'false')
    # Start Kafka consumer in Celery
    consume_kafka_messages.delay(
        topic=TOPIC,
        group_id=GRP_ID,
        config=read_config()
    )

class ManageConversationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'manage_conversation'

    def ready(self):
        # Init signals
        #import manage_conversation.signals
        # Init kafka consume tasks with celery/redis
        #start_kafka_consumer_task()
        pass
