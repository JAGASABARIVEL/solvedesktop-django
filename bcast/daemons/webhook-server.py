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
import base64
import json
import re
from html import escape

from flask import Flask, request, jsonify

from confluent_kafka import Producer, KafkaError

from bs4 import BeautifulSoup

from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

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
        "message.max.bytes": 1000000000,  # 953 MB - MAX allowed
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


def extract_plain_text(payload):
    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8")
        elif part.get("parts"):
            return extract_plain_text(part)
    return "[No Text]"


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

"""
def extract_attachments(service, user_id, payload, msg_id):
    attachments = []
    def walk_parts(parts):
        for part in parts:
            filename = part.get("filename")
            body = part.get("body", {})
            mime_type = part.get("mimeType", "")
            attachment_id = body.get("attachmentId")
            if filename and attachment_id:
                attachment = service.users().messages().attachments().get(
                    userId=user_id, messageId=msg_id, id=attachment_id
                ).execute()
                data = base64.urlsafe_b64decode(attachment.get("data").encode("UTF-8"))
                file_path = os.path.join(base_path, filename)
                with open(file_path, "wb") as f:
                    f.write(data)
                attachments.append({
                    "filename": filename,
                    "mime_type": mime_type,
                    "data_base64": base64.b64encode(data).decode("utf-8")
                })
            elif part.get("parts"):
                walk_parts(part["parts"])
    if payload.get("parts"):
        walk_parts(payload["parts"])
    return attachments
"""

import base64
import os
import time

def extract_attachments(service, user_id, payload, msg_id, sender_email):
    attachments = []
    # Create a unique path for this message's attachments
    timestamp = str(time.time())
    base_path = f"/tmp/{sender_email}/{timestamp}"
    os.makedirs(base_path, exist_ok=True)
    def walk_parts(parts):
        for part in parts:
            filename = part.get("filename")
            body = part.get("body", {})
            mime_type = part.get("mimeType", "")
            attachment_id = body.get("attachmentId")
            if filename and attachment_id:
                attachment = service.users().messages().attachments().get(
                    userId=user_id, messageId=msg_id, id=attachment_id
                ).execute()
                data = base64.urlsafe_b64decode(attachment.get("data").encode("UTF-8"))
                file_path = os.path.join(base_path, filename)
                with open(file_path, "wb") as f:
                    f.write(data)
                attachments.append({
                    "filename": filename,
                    "mime_type": mime_type,
                    "path": file_path
                })
            elif part.get("parts"):
                walk_parts(part["parts"])

    if payload.get("parts"):
        walk_parts(payload["parts"])
    return attachments



def extract_html_or_plain_part(payload):
    if payload.get("mimeType") == "text/html":
        data = payload.get("body", {}).get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data.encode("UTF-8")).decode("UTF-8", errors="ignore")
            return "text/html", decoded
    elif payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data.encode("UTF-8")).decode("UTF-8", errors="ignore")
            return "text/plain", decoded
    # If this is a multipart message, check sub-parts recursively
    for part in payload.get("parts", []):
        mime_type, decoded = extract_html_or_plain_part(part)
        if mime_type:
            return mime_type, decoded
    return None, None


def sanitize_html_links(html):
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a"):
        a.attrs.pop("href", None)  # Remove href
        a.attrs.pop("target", None)  # Remove target if present
        a.attrs.pop("rel", None)     # Remove rel if present
    return str(soup)


def disable_links(html):
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a"):
        span = soup.new_tag("span")
        span.string = a.get_text()
        a.replace_with(span)
    return str(soup)


@app.route("/webhook/gmail/push", methods=["POST"])
def gmail_push_webhook():
    logger.info(f"📥 Gmail Webhook Payload: {request.data}")
    try:
        envelope = json.loads(request.data)
        pubsub_message = envelope.get("message", {})
        encoded_data = pubsub_message.get("data")
        if not encoded_data:
            return jsonify({"error": "Missing data"}), 400

        decoded_bytes = base64.b64decode(encoded_data)
        decoded_json = json.loads(decoded_bytes)

        email_address = decoded_json.get("emailAddress")
        new_history_id = decoded_json.get("historyId")

        if not email_address or not new_history_id:
            logger.warning("Missing email or historyId")
            return jsonify({"error": "Missing fields"}), 400

        logger.info(f"📬 Gmail push for {email_address}, historyId={new_history_id}")

        # Fetch GmailAccount info
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, access_token, refresh_token, history_id
                    FROM manage_platform_gmailaccount
                    WHERE email_address = %s AND active = TRUE
                    LIMIT 1
                """, (email_address,))
                row = cursor.fetchone()
                logger.info(f"Found from manage_platform_gmailaccount {row}")
                if not row:
                    logger.error(f"Gmail account {email_address} not found or not active")
                    return jsonify({"error": "Gmail account not found or not active"}), 404
                account_id, access_token, refresh_token, last_stored_history_id = row

        if not last_stored_history_id:
            logger.warning("🚫 No previous history ID stored. Skipping fetch.")
            return jsonify({"error": "No previous history ID"}), 400

        # Setup credentials
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=config("GOOGLE_CLIENT_ID"),
            client_secret=config("GOOGLE_CLIENT_SECRET")
        )

        logger.info(f"creds.valid {creds.valid} | creds.expired {creds.expired} | creds {creds}")
        # Refresh if needed
        if not creds.valid or creds.expired:
            logger.info("🔁 Refreshing expired access token...")
            creds.refresh(Request())
            access_token = creds.token
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE manage_platform_gmailaccount
                        SET access_token=%s,
                            token_expiry=%s,
                            updated_at=NOW()
                        WHERE id=%s
                    """, (creds.token, creds.expiry, account_id))

        # Use Gmail API
        service = build('gmail', 'v1', credentials=creds)

        try:
            history = service.users().history().list(
                userId='me',
                startHistoryId=last_stored_history_id,
                historyTypes=['messageAdded']
            ).execute()
        except RefreshError as refresh_error:
            logger.error(f"❌ Refresh failed after 401: {refresh_error}")
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE manage_platform_gmailaccount
                        SET active=FALSE,
                            updated_at=NOW()
                        WHERE id=%s
                    """, (account_id,))
            return jsonify({"error": "OAuth refresh failed. Reauthorization required."}), 401
        logger.info(f"🔍 Gmail History keys: {history.keys()}")
        logger.info(f"📚 Gmail history content: {json.dumps(history)}")

        with get_conn() as conn:
            with conn.cursor() as cursor:
                for record in history.get("history", []):
                    for msg_meta in record.get("messages", []):
                        msg_id = msg_meta["id"]
                        # Check duplicate
                        cursor.execute("""
                            SELECT 1 FROM manage_platform_processedgmailmessage
                            WHERE gmail_account_id = %s AND message_id = %s
                            LIMIT 1
                        """, (account_id, msg_id))
                        if cursor.fetchone():
                            logger.info(f"⏩ Already processed message {msg_id}")
                            continue
                        # Fetch full message
                        #message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                        try:
                            message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                        except HttpError as e:
                            if e.resp.status == 404:
                                logger.warning(f"⚠️ Message {msg_id} not found. Skipping.")
                                continue
                            else:
                                logger.warning("Exception while processing the message")
                                raise  # re-raise other errors
                        content_blocks = []
                        headers = {h["name"]: h["value"] for h in message.get("payload", {}).get("headers", [])}
                        sender = headers.get("From")
                        if not sender:
                            # Save processed msg_id
                            cursor.execute("""
                                INSERT INTO manage_platform_processedgmailmessage
                                (gmail_account_id, message_id, processed_at)
                                VALUES (%s, %s, NOW())
                            """, (account_id, msg_id))
                            continue
                        gmail_message_id = headers.get("Message-ID")
                        gmail_thread_id = message.get("threadId")
                        subject = headers.get("Subject", "No Subject")  # fallback
                        attachments = extract_attachments(service, "me", message.get("payload", {}), msg_id, sender)
                        logger.info(f"📎 Found {len(attachments)} attachments")
                        timestamp = int(message.get("internalDate", 0)) // 1000
                        # Extract raw HTML or plain
                        mime_type, raw_content = extract_html_or_plain_part(message.get("payload", {}))
                        logger.info(f"✉️ Extracted mime_type: {mime_type}")
                        #if mime_type == "text/html" and raw_content:
                        #    content_blocks = [{"type": "html", "html": raw_content}]
                        if mime_type == "text/html" and raw_content:
                            cleaned_html = disable_links(raw_content)
                            content_blocks = [{"type": "html", "html": cleaned_html}]
                        elif mime_type == "text/plain" and raw_content:
                            plain_clean = re.sub(r'^>+', '', raw_content, flags=re.MULTILINE)
                            html_wrapped = f"<pre>{escape(plain_clean)}</pre>"
                            content_blocks = [{"type": "html", "html": html_wrapped}]
                        else:
                            content_blocks = []
                        logger.info(f": content_blocks {content_blocks}")
                        attachment_path = f"/tmp/{sender}/"
                        # Push to Kafka
                        send_msg_from_customer(
                            phone_number_id=email_address,
                            recipient_id=sender,
                            message_body='',
                            subject=subject,
                            content_blocks = content_blocks,
                            attachments=attachments,
                            message_id=gmail_message_id,
                            thread_id=gmail_thread_id,
                            msg_type="email",
                            msg_from_type="CUSTOMER",
                            app_name="GMAIL"
                        )

                        # Save processed msg_id
                        cursor.execute("""
                            INSERT INTO manage_platform_processedgmailmessage
                            (gmail_account_id, message_id, processed_at)
                            VALUES (%s, %s, NOW())
                        """, (account_id, msg_id))

                logger.warning("Message processing complete and returning")
                # ✅ Finally, update the last stored historyId with this one
                cursor.execute("""
                    UPDATE manage_platform_gmailaccount
                    SET history_id=%s, updated_at = NOW()
                    WHERE id=%s
                """, (new_history_id, account_id))

        status = {"status": "Published to Kafka"}
        logger.info(f"Returning status {status}")
        return jsonify(status), 200

    except Exception as e:
        logger.error(f"💥 Gmail webhook error: {e}")
        return jsonify({"error": str(e)}), 500



start_background_tasks()

if __name__ == '__main__':
    app.run(port=5000, host='0.0.0.0', debug=False)
