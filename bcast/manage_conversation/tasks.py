import os
import json
import time
#import redis
from celery import shared_task
from confluent_kafka import Consumer as ConfluentConsumer, KafkaError
from django.conf import settings
from .models import Conversation, IncomingMessage, UserMessage


@shared_task(bind=True, queue='kafka_consumer_queue')
def consume_kafka_messages(self, topic, group_id, config):
    consumer_config = config
    consumer_config['group.id'] = group_id
    consumer_config['auto.offset.reset'] = 'earliest'
    consumer = ConfluentConsumer(consumer_config)
    consumer.subscribe([topic])
    #redis_client = redis.StrictRedis.from_url(settings.CELERY_BROKER_URL)

    try:
        while True:
            #if redis_client.get("STOP_KAFKA_CONSUMER") == b"1":
            #    print("Stopping Kafka consumer based on stop signal.")
            #    break
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    print(f"End of partition reached: {msg.error()}")
                else:
                    print(f"Consumer error: {msg.error()}")
                continue
            try:
                message_value = json.loads(msg.value().decode('utf-8'))
                process_message(message_value)
            except Exception as e:
                import traceback
                traceback.print_exc()
                continue
            time.sleep(2) # No messages and hence sleeping to avoid blocking CPU cycles
    finally:
        consumer.close()
        # Ensure lock is removed on exit
        if os.path.exists(settings.LOCK_FILE):
            os.remove(settings.LOCK_FILE)

def process_message(message):
    if message["msg_from_type"] == "CUSTOMER":
        handle_customer_message(message)
    elif message["msg_from_type"] == "ORG":
        handle_org_message(message)


from django.apps import apps


def handle_customer_message(msg_data):
    recipient_id = msg_data['recipient_id']
    message_body = msg_data['message_body']
    phone_number_id = msg_data['phone_number_id']

    platform_model = apps.get_model(settings.PLATFORM_MODEL)
    platform = platform_model.objects.filter(login_id=phone_number_id).first()

    org_model = apps.get_model(settings.ORG_MODEL)
    organization = org_model.objects.filter(owner_id=platform.owner_id).first()

    contact_model = apps.get_model(settings.CONTACT_MODEL)
    contact, _ = contact_model.objects.get_or_create(
        phone=recipient_id,
        defaults={
            'name': '',
            'organization': organization,
            'created_by': organization.owner
        }
    )

    conversation, _ = Conversation.objects.get_or_create(
        organization=organization,
        platform=platform,
        contact=contact,
        status__in=['new', 'active'],
        defaults={"open_by": "customer"}
    )

    IncomingMessage.objects.create(
        conversation=conversation,
        contact=contact,
        organization=organization,
        platform=platform,
        message_body=message_body
    )

def handle_org_message(msg_data):
    message_id = msg_data['message_id']
    message_status = msg_data['message_status']
    error_details = msg_data.get("error_details", None)

    user_message = UserMessage.objects.filter(messageid=message_id).first()
    if user_message:
        user_message.status = message_status
        if error_details:
            user_message.status_details = json.dumps(error_details)
        user_message.save()

        IncomingMessage.objects.filter(conversation=user_message.conversation).update(status="responded")
