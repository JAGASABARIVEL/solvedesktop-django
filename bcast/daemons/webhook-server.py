import os
import json
import traceback
import logging
import time
from threading import Thread
import hmac
import hashlib
import psycopg2
from contextlib import contextmanager

from flask import Flask, request, jsonify
from confluent_kafka import Producer, KafkaError

from decouple import config

db_driver = psycopg2

@contextmanager
def get_conn(auto_commit=True):
    conn = db_driver.connect(
        dbname=config("PG_DB"),
        user=config("PG_USER"),
        password=config("PG_PASSWORD"),
        host=config("PG_HOST", "localhost"),
        port=config("PG_PORT", "5432")
    )
    try:
        yield conn
        if auto_commit:
            conn.commit()
    except Exception:
        import traceback
        traceback.print_exc()
        raise  # re-raise so caller knows about it
    finally:
        conn.close()


def get_secret_key_by_login_id(login_id: str):
    query = """
    SELECT secret_key FROM manage_platform_platform
    WHERE login_id = %s
    LIMIT 1
    """
    # Replace your_app_platform with your actual table name (usually app_label + model_name lowercase)

    with get_conn(auto_commit=False) as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (login_id,))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                return None

app = Flask(__name__)

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Kafka Configuration
TOPIC = 'whatsapp'

def read_config():
    return {
        "bootstrap.servers": "localhost:9092",
        "client.id": "jackdesk-webhook-1",
        "acks": "all",
        "retries": 3
    }

producer_config = read_config()

# Replace with your actual tokens
VERIFY_TOKEN = config("WHA_VERIFY_TOKEN")

# Initialize Kafka Producer
producer = Producer(producer_config)

time.sleep(5)
print("Producer is ready to produce")

def flush_kafka_messages_consistently():
    while True:
        producer.flush()
        time.sleep(2)

def start_background_tasks():
    flush_thread = Thread(target=flush_kafka_messages_consistently, daemon=True)
    flush_thread.start()

def delivery_report(err, msg):
    """
    Callback for delivery reports. Logs the delivery result.
    """
    if err is not None:
        logger.error(f"Message delivery failed: {err}")
    else:
        logger.info(f"Message delivered to {msg.topic()} [{msg.partition()}]")

def publish_message(topic, msg):
    """
    Publishes a message to Kafka asynchronously.
    """
    try:
        producer.produce(
            topic,
            value=json.dumps(msg),
            callback=delivery_report
        )
        print("Producer produced message")
    except KafkaError as e:
        logger.error(f"Failed to produce message: {e}")

def send_msg_from_org(**kwargs):
    try:
        publish_message(TOPIC, kwargs)
    except Exception as e:
        logger.error(f"Error sending message: {e}")

def send_msg_from_customer(**kwargs):
    """
    Formats and publishes a message to Kafka.
    """
    try:
        publish_message(TOPIC, kwargs)
    except Exception as e:
        logger.error(f"Error sending message: {e}")


def verify_signature(request, phone_number_id):
    """
    Verifies that the request is from Facebook using SHA-256 HMAC signature.
    """
    signature = request.headers.get('X-Hub-Signature-256')
    logger.info("Validating signature")
    if not signature:
        logger.error("Signature is empty")
        return False

    try:
        sha_name, signature = signature.split('=')
        if sha_name != 'sha256':
            logger.error("SHA does not match")
            return False
    except ValueError:
        logger.error("Value error while trying to get signature")
        return False

    secret_key = get_secret_key_by_login_id(phone_number_id)
    if not secret_key:
        logger.error("Secret key not found for the phone number")
        return False
    mac = hmac.new(secret_key.encode(), msg=request.data, digestmod=hashlib.sha256)
    expected_signature = mac.hexdigest()
    return hmac.compare_digest(expected_signature, signature)


@app.route('/whatsapp', methods=['GET', 'POST'])
def whatsapp_webhook():
    """
    Handles WhatsApp webhook events.
    """
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if not challenge:
            logger.warning("Challenge not provided")
            return "Forbidden", 403
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            logger.info("Webhook verified successfully")
            return challenge, 200
        else:
            logger.warning("Webhook verification failed")
            return "Forbidden", 403

    elif request.method == 'POST':
        try:
            data = request.get_json()
            logger.info(f"Received data: {data}")
            value = data.get('entry', [{}])[0].get('changes', [{}])[0].get('value', {})
            phone_number_id = value.get('metadata', {}).get('phone_number_id')
            if not phone_number_id:
                logger.error("Phone number is empty")
                return jsonify({"status": "error", "message": "Phone number is empty"}), 400
            if not verify_signature(request, phone_number_id):
                logger.warning("Invalid signature. Possible spoofed request.")
                return jsonify({"status": "error", "message": "Invalid signature"}), 403
            if value.get('statuses'):
                recipient_id = value['statuses'][0].get('recipient_id')
                status = value['statuses'][0].get('status')
                for status in value['statuses']:
                    message_id = status.get("id")
                    message_status = status.get("status")
                    recipient_id = status.get("recipient_id")
                    error_details = None
                    if message_status == 'failed':
                        error_details = status.get('errors', [{}])
                    send_msg_from_org(
                        phone_number_id=phone_number_id,
                            recipient_id=recipient_id,
                            message_id=message_id,
                            message_status=message_status,
                            error_details=error_details,
                            msg_from_type="ORG",
                            app_name="WHATSAPP"
                    )
                logger.info(f"Status update: {status}, Error: {error_details}")
            elif value.get('messages'):
                messages = value['messages']
                for message in messages:
                    recipient_id = message.get('from')
                    logger.info(f"Received message details {recipient_id}: {message}")
                    if message.get('type') == 'text':
                        text_message = message['text']['body']
                        logger.info(f"Received text message details {recipient_id}: {text_message}")
                        send_msg_from_customer(
                            phone_number_id=phone_number_id,
                                recipient_id=recipient_id,
                                message_body=text_message,
                                msg_type="text",
                                msg_from_type="CUSTOMER",
                                app_name="WHATSAPP"
                        )
                    elif message.get('type') == 'document':
                        media_id = message['document']['id']
                        mime_type = message['document']['mime_type']
                        filename = message['document'].get('filename')
                        caption = message['document'].get('caption')
                        body_to_send = {"caption": caption, "media_id": media_id}
                        if filename:
                            body_to_send.update({"filename": filename})
                        send_msg_from_customer(
                            phone_number_id=phone_number_id,
                                recipient_id=recipient_id,
                                message_body=body_to_send,
                                msg_type=mime_type,
                                msg_from_type="CUSTOMER",
                                app_name="WHATSAPP"
                        )
                    elif message.get('type') == 'image':
                        media_id = message['image']['id']
                        caption = message['image'].get('caption')#else "image_" + str(media_id)
                        mime_type = message['image']['mime_type']
                        body_to_send = {"caption": caption, "media_id": media_id}
                        send_msg_from_customer(
                            phone_number_id=phone_number_id,
                                recipient_id=recipient_id,
                                message_body=body_to_send,
                                msg_type=mime_type,
                                msg_from_type="CUSTOMER",
                                app_name="WHATSAPP"
                        )
                    elif message.get('type') == 'audio':
                        audio = message['audio']
                        body_to_send = {
                            "media_id": audio['id'],
                            "mime_type": audio.get('mime_type'),
                            "voice": audio.get('voice', False),
                            "sha256": audio.get('sha256')
                        }
                        send_msg_from_customer(
                            phone_number_id=phone_number_id,
                            recipient_id=recipient_id,
                            message_body=body_to_send,
                            msg_type=audio.get('mime_type') or "audio",
                            msg_from_type="CUSTOMER",
                            app_name="WHATSAPP"
                        )
                    elif message.get('type') == 'location':
                        loc = message['location']
                        body_to_send = {
                            "latitude": loc.get('latitude'),
                            "longitude": loc.get('longitude')
                        }
                        send_msg_from_customer(
                            phone_number_id=phone_number_id,
                            recipient_id=recipient_id,
                            message_body=body_to_send,
                            msg_type="location",
                            msg_from_type="CUSTOMER",
                            app_name="WHATSAPP"
                        )
                    elif message.get('type') == 'contacts':
                        contacts = message.get('contacts', [])
                        contact_details = []
                        for contact in contacts:
                            name = contact.get('name', {})
                            phones = contact.get('phones', [])
                            contact_details.append({
                                "name": name.get("formatted_name"),
                                "first_name": name.get("first_name"),
                                "phones": phones
                            })
                        send_msg_from_customer(
                            phone_number_id=phone_number_id,
                            recipient_id=recipient_id,
                            message_body=contact_details,
                            msg_type="contacts",
                            msg_from_type="CUSTOMER",
                            app_name="WHATSAPP"
                        )
                    elif message.get('type') == 'video':
                        vid = message['video']
                        body_to_send = {
                            "media_id": vid['id'],
                            "mime_type": vid.get('mime_type'),
                            "sha256": vid.get('sha256')
                        }
                        send_msg_from_customer(
                            phone_number_id=phone_number_id,
                            recipient_id=recipient_id,
                            message_body=body_to_send,
                            msg_type=vid.get('mime_type') or "video",
                            msg_from_type="CUSTOMER",
                            app_name="WHATSAPP"
                        )
                    else:
                        logger.info(f"Unsupported message type {message.get('type')}")
            return jsonify({"status": "success"}), 200
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            logger.debug(traceback.format_exc())
            return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/messenger', methods=['GET', 'POST'])
def messenger_webhook():
    """
    Handles messenger webhook events.
    """
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if not challenge:
            logger.warning("Challenge not provided")
            return "Forbidden", 403
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            logger.info("Webhook verified successfully")
            return challenge, 200
        else:
            logger.warning("Webhook verification failed for messenger")
            return "Forbidden", 403

    elif request.method == 'POST':
        try:
            data = request.get_json()
            logger.info(f"Received messenger data: {data}")
            for entry in data.get('entry'):
                page_owner_id = entry.get('id')
                for messaging in entry.get('messaging'):
                    sender_id = messaging.get('sender')
                    timestamp = messaging.get("timestamp")
                    message_status = None
                    message_status = "delivered" if messaging.get('delivery') else message_status
                    message_status = "read" if messaging.get('read') else message_status
                    message_status = "message" if messaging.get('message') else message_status
                    if message_status in ("delivered", "read"):
                        timestamp = messaging.get("delivery", {}).get("watermark") if message_status == "delivered" else messaging.get("read", {}).get("watermark")
                        # Its a ORG notification
                        send_msg_from_org(
                            page_owner_id=page_owner_id,
                                sender_id=sender_id,
                                message_status=message_status,
                                timestamp=timestamp,
                                msg_from_type="ORG",
                                app_name="MESSENGER"
                        )
                    elif message_status in ("message",):
                        # Its a new customer message
                        send_msg_from_customer(
                            page_owner_id=page_owner_id,
                                sender_id=sender_id,
                                message_status=message_status,
                                msg=messaging.get('message').get("text"),
                                timestamp=timestamp,
                                msg_type="text",
                                msg_from_type="CUSTOMER",
                                app_name="MESSENGER"
                        )
                    else:
                        logger.info(f"Unsupported message type {message_status}")
            return jsonify({"status": "Processed"}), 200
        except Exception as e:
            logger.error(f"Error processing messenger webhook: {e}")
            logger.debug(traceback.format_exc())
            return jsonify({"status": "error", "message": str(e)}), 400



#from yourapp.models import get_gmail_account_by_email
#from yourapp.utils import poll_history
import base64
@app.route("/webhook/gmail/push", methods=["POST"])
def gmail_push_webhook():
    logger.info(f"Received notification from pub/sub google {request.data}")

    try:
        # Step 1: Parse the outer message JSON
        envelope = json.loads(request.data)

        # Step 2: Decode base64 "data" field inside "message"
        pubsub_message = envelope.get("message", {})
        encoded_data = pubsub_message.get("data")

        if not encoded_data:
            logger.warning("Missing data in Pub/Sub message.")
            return jsonify({"error": "Missing data"}), 400

        # Step 3: Decode Base64 and parse JSON
        decoded_bytes = base64.b64decode(encoded_data)
        decoded_json = json.loads(decoded_bytes)

        # Step 4: Extract email and historyId
        email_address = decoded_json.get("emailAddress")
        history_id = decoded_json.get("historyId")

        if not email_address:
            logger.warning("Email address not found in decoded data.")
            return jsonify({"error": "Missing email"}), 400

        logger.info(f"Received Gmail notification for {email_address}, historyId: {history_id}")

        # TODO: Look up your account model by email and call poll_history(account, history_id)
        #account = get_gmail_account_by_email(email_address)
        #if not account:
        #    return jsonify({"error": "Account not found"}), 404
        #poll_history(account)
        logger.info(f"Received email notification {email_address}")
        return jsonify({"status": "Processed"}), 200
    except Exception as webhook_error:
        logger.info(f"Error while processing the webhook notification {webhook_error}")
        return jsonify({"error": "Issue while processing webhook notification"}), 400



start_background_tasks()

if __name__ == '__main__':
    app.run(port=5000, host='0.0.0.0', debug=False)