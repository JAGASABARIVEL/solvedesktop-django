import os
import json
import time
import logging
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta
from io import BytesIO
import sqlite3
import mimetypes
import pytz

import jwt
import psycopg2
from psycopg2.extras import RealDictCursor  # if using PostgreSQL
import boto3
from botocore.client import Config
import socketio
import requests
from confluent_kafka import Consumer as ConfluentConsumer, KafkaError
from decouple import config

os.environ["PRODUCTION"] = config("PRODUCTION")
os.environ["SQLITE_DB"] = 'db.sqlite3'
if os.getenv("PRODUCTION") == '1':
    os.environ["KAFKA_CONFIG_GRP_ID"] = "whatsapp-grp-cloud"
else:
    os.environ["KAFKA_CONFIG_GRP_ID"] = "whatsapp-grp-dev"
os.environ["PG_DB"] = config("PG_DB")
os.environ["PG_HOST"] = config("PG_HOST")
os.environ["PG_PORT"] = config("PG_PORT")
os.environ["PG_USER"] = config("PG_USER")
os.environ["PG_PASSWORD"] = config("PG_PASSWORD")
os.environ["B2_ENDPOINT_URL"] = config("B2_ENDPOINT_URL")
os.environ["B2_ACCESS_KEY_ID"] = config("B2_ACCESS_KEY_ID")
os.environ["B2_SECRET_ACCESS_KEY"] = config("B2_SECRET_ACCESS_KEY")
os.environ["B2_STORAGE_BUCKET_NAME"] = config("B2_STORAGE_BUCKET_NAME")
if os.getenv("PRODUCTION") == '1':
    os.environ["SOCKET_URL"] = "https://solvedesktop.onrender.com?token={access_token}"
else:
    os.environ["SOCKET_URL"] = "http://localhost:5001?token={access_token}"

def generate_forever_token():
    payload = {
        "role": "backend",
        "service": "bcast_backend",
    }
    secret_key = config("DRF_KEY")
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    return token


class WhatsAppKafkaConsumer:
    def __init__(self):
        self.use_sqlite = os.getenv("PRODUCTION") == '0'
        self.db_driver = sqlite3 if self.use_sqlite else psycopg2
        self.db_file = os.getenv("SQLITE_DB", "dev.sqlite3")
        self.topic = "whatsapp"
        self.group_id = os.getenv("KAFKA_CONFIG_GRP_ID")
        self.sio = socketio.Client()
        self.access_token = generate_forever_token()
        if not self.access_token:
            raise Exception("Cannot generate access token to connect with websocket server")
        self.sio.connect(os.getenv("SOCKET_URL").format(access_token=self.access_token))

        @self.sio.on("website_chatwidget_messages_front_to_back")
        def on_website_chatwidget_messages(data):
            self.handle_website_chatwidget_messages(data)

        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    @contextmanager
    def get_conn(self, auto_commit=True):
        conn = (
            self.db_driver.connect(self.db_file)
            if self.use_sqlite
            else self.db_driver.connect(
                dbname=os.getenv("PG_DB"),
                user=os.getenv("PG_USER"),
                password=os.getenv("PG_PASSWORD"),
                host=os.getenv("PG_HOST", "localhost"),
                port=os.getenv("PG_PORT", "5432")
            )
        )
        try:
            yield conn
            if auto_commit:
                conn.commit()
        except Exception:
            traceback.print_exc()
        finally:
            conn.close()

    @property
    def param(self):
        return '?' if self.use_sqlite else '%s'

    def read_config(self):
        return {
            "bootstrap.servers": config("SERVER"),
            #"security.protocol": config("PROTOCOL"),
            #"sasl.mechanisms": config("MECHANISM"),
            #"sasl.username": config("UNAME"),
            #"sasl.password": config("PASSWORD"),
            "session.timeout.ms": config("TIMEOUT_MS"),
            "client.id": config("CLIENTID"),
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True
        }
    
    def process_message(self, message):
        if message["msg_from_type"] == "CUSTOMER":
            self.handle_customer_messages(message)
        elif message["msg_from_type"] == "ORG":
            self.handle_org_messages(message)

    def handle_customer_messages(self, message):
        if message["app_name"] == "WHATSAPP":
            self.handle_customer_message_whatsapp(message)
        elif  message["app_name"] == "MESSENGER":
            self.handle_customer_message_messenger(message)

    def handle_org_messages(self, message):
        if message["app_name"] == "WHATSAPP":
            self.handle_org_message_whatsapp(message)
        elif  message["app_name"] == "MESSENGER":
            self.handle_org_message_messenger(message)

    def requests_auth_header(self, token):
        return {"Authorization": f"Bearer {token}"}

    @contextmanager
    def download_from_provider(self, media_id, access_token):
        file_data = None
        try:
            auth_header=self.requests_auth_header(access_token) 
            media_info_response = requests.get(
                f"https://graph.facebook.com/v18.0/{media_id}",
                headers=auth_header
            )
            if media_info_response.status_code not in range(200, 299):
                self.logger.info(f"Failed to get the download url due to status code {media_info_response.status_code}")
                raise Exception(f"Failed to get the download url due to status code {media_info_response.status_code}")
            media_info = media_info_response.json()
            media_url = media_info.get("url")
            if media_url:
                media_file_response = requests.get(media_url, headers=auth_header, stream=True)
                if media_file_response.status_code == 200:
                    file_data = BytesIO(media_file_response.content)
                else:
                    raise Exception(f"Failed to download media: {media_file_response.status_code}")
            yield file_data
        except Exception as download_exception:
            raise download_exception
        finally:
            if file_data:
                file_data.close()

    def provide_permission(self, cursor, org_id, file_id, user_id):
        cursor.execute(f"""
            SELECT user_id FROM manage_users_enterpriseprofile 
            WHERE organization_id={self.param};
        """, (org_id,))
        employees = cursor.fetchall()
        for employee in employees:
            # employee[0] because the result returned is a tuple (1,)
            if employee[0] == user_id:
                # Skipping the owner since he already has permission being the creator
                continue
            cursor.execute(f"""
                INSERT INTO manage_files_filepermission (
                    file_id, user_id, inherited, can_read, can_write
                ) VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param})
                ON CONFLICT (file_id, user_id)
                DO UPDATE SET
                    inherited = EXCLUDED.inherited,
                    can_read = EXCLUDED.can_read,
                    can_write = EXCLUDED.can_write;
            """, (file_id, employee[0], True, True, True))

    

    def generate_presigned_url(self, s3_client, object_key, expiry_seconds=3600):
        # Guess the MIME type from the object_key
        content_type, _ = mimetypes.guess_type(object_key)
        if content_type is None:
            content_type = 'application/octet-stream'  # Fallback for unknown types
    
        url = s3_client.generate_presigned_url(
            ClientMethod='get_object',
            Params={
                'Bucket': os.getenv("B2_STORAGE_BUCKET_NAME"),
                'Key': object_key,
                'ResponseContentDisposition': 'inline',
                'ResponseContentType': content_type,
            },
            ExpiresIn=expiry_seconds
        )
        return url

    def save_media_file_to_s3_raw_sql(self, conn, user_identifier: str, receiver_name: str, filename: str, file_data: BytesIO):
        # 1. Look up user and org
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT u.id, ep.organization_id, o.name
            FROM manage_users_customuser u
            JOIN manage_users_enterpriseprofile ep ON ep.user_id = u.id
            JOIN manage_organization_organization o ON o.id = ep.organization_id
            WHERE u.email={self.param}
            LIMIT 1;
        """, (user_identifier,))
        row = cursor.fetchone()
        if not row:
            raise Exception("User or their organization not found.")
        user_id, org_id, org_name = row
        org_name = org_name.replace(" ", "_")
        uname = user_identifier.split('@')[0] if '@' in user_identifier else user_identifier
        today = datetime.now().strftime('%Y-%m-%d')
        size_gb = file_data.getbuffer().nbytes / 1_000_000_000
        customer_directory = "customer"
        received_directory_name = "received"
        receiver_directory = receiver_name.replace(" ", "_")
    
        # 2. Generate folder paths

        home_directory_key = f"{uname}/"
        org_directory_key = f"{home_directory_key}{org_name}/"
        customer_directory_key = f"{org_directory_key}{customer_directory}/"
        received_directory_key = f"{customer_directory_key}{received_directory_name}/"
        receiver_folder_key = f"{received_directory_key}{receiver_directory}/"
        date_folder_key = f"{receiver_folder_key}{today}/"
        file_key = f"{date_folder_key}{filename}"

        # 3. Upload folder placeholder and file to S3
        s3 = boto3.client(
            's3',
            endpoint_url=os.getenv("B2_ENDPOINT_URL"),
            aws_access_key_id=os.getenv("B2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("B2_SECRET_ACCESS_KEY"),
            config=Config(signature_version="s3v4"),
            region_name='us-west-002'  # ✅ Add your correct region name here if required
        )

        s3.put_object(Bucket=os.getenv("B2_STORAGE_BUCKET_NAME"), Key=home_directory_key)
        s3.put_object(Bucket=os.getenv("B2_STORAGE_BUCKET_NAME"), Key=org_directory_key)
        s3.put_object(Bucket=os.getenv("B2_STORAGE_BUCKET_NAME"), Key=customer_directory_key)
        s3.put_object(Bucket=os.getenv("B2_STORAGE_BUCKET_NAME"), Key=received_directory_key)
        s3.put_object(Bucket=os.getenv("B2_STORAGE_BUCKET_NAME"), Key=receiver_folder_key)
        s3.put_object(Bucket=os.getenv("B2_STORAGE_BUCKET_NAME"), Key=date_folder_key)
        s3.upload_fileobj(file_data, os.getenv("B2_STORAGE_BUCKET_NAME"), file_key)

        parent = None

        # 5. Insert user home folder if not exists
        cursor.execute(f"""
            SELECT id FROM manage_files_file 
            WHERE s3_key={self.param} AND owner_id={self.param} AND is_deleted={self.param}
            LIMIT 1;
        """, (home_directory_key, user_id, False))
        receiver_row = cursor.fetchone()
        if receiver_row:
            parent = receiver_row[0]
        else:
            cursor.execute(f"""
                INSERT INTO manage_files_file (name, owner_id, s3_key, parent_id, created_at, size_gb, is_deleted)
                VALUES ({self.param}, {self.param}, {self.param}, NULL, CURRENT_TIMESTAMP, 0, {self.param})
                RETURNING id;
            """, (uname, user_id, home_directory_key, False))
            parent =  cursor.fetchone()[0]
        self.provide_permission(cursor, org_id, parent, user_id)

        # 4. Insert org folder if not exists
        cursor.execute(f"""
            SELECT id FROM manage_files_file 
            WHERE s3_key={self.param} AND owner_id={self.param} AND is_deleted={self.param}
            LIMIT 1;
        """, (org_directory_key, user_id, False))
        receiver_row = cursor.fetchone()
        if receiver_row:
            parent = receiver_row[0]
        else:
            cursor.execute(f"""
                INSERT INTO manage_files_file (name, owner_id, s3_key, parent_id, created_at, size_gb, is_deleted)
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP, 0, {self.param})
                RETURNING id;
            """, (org_name, user_id, org_directory_key, parent, False))
            parent =  cursor.fetchone()[0]
        self.provide_permission(cursor, org_id, parent, user_id)

        # 6. Insert customer folder if not exists
        cursor.execute(f"""
            SELECT id FROM manage_files_file 
            WHERE s3_key={self.param} AND owner_id={self.param} AND is_deleted={self.param}
            LIMIT 1;
        """, (customer_directory_key, user_id, False))
        receiver_row = cursor.fetchone()
        if receiver_row:
            parent = receiver_row[0]
        else:
            cursor.execute(f"""
                INSERT INTO manage_files_file (name, owner_id, s3_key, parent_id, created_at, size_gb, is_deleted)
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP, 0, {self.param})
                RETURNING id;
            """, (customer_directory, user_id, customer_directory_key, parent, False))
            parent =  cursor.fetchone()[0]
        self.provide_permission(cursor, org_id, parent, user_id)
        
        # 7. Insert received folder if not exists
        cursor.execute(f"""
            SELECT id FROM manage_files_file 
            WHERE s3_key={self.param} AND owner_id={self.param} AND is_deleted={self.param}
            LIMIT 1;
        """, (received_directory_key, user_id, False))
        receiver_row = cursor.fetchone()
        if receiver_row:
            parent = receiver_row[0]
        else:
            cursor.execute(f"""
                INSERT INTO manage_files_file (name, owner_id, s3_key, parent_id, created_at, size_gb, is_deleted)
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP, 0, {self.param})
                RETURNING id;
            """, (received_directory_name, user_id, received_directory_key, parent, False))
            parent =  cursor.fetchone()[0]
        self.provide_permission(cursor, org_id, parent, user_id)

        # 8. Insert receiver folder if not exists
        cursor.execute(f"""
            SELECT id FROM manage_files_file 
            WHERE s3_key={self.param} AND owner_id={self.param} AND is_deleted={self.param}
            LIMIT 1;
        """, (receiver_folder_key, user_id, False))
        receiver_row = cursor.fetchone()
        if receiver_row:
            parent = receiver_row[0]
        else:
            cursor.execute(f"""
                INSERT INTO manage_files_file (name, owner_id, s3_key, parent_id, created_at, size_gb, is_deleted)
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP, 0, {self.param})
                RETURNING id;
            """, (receiver_directory, user_id, receiver_folder_key, parent, False))
            parent =  cursor.fetchone()[0]
        self.provide_permission(cursor, org_id, parent, user_id)

        # 9. Insert date folder under receiver folder if not exists
        cursor.execute(f"""
            SELECT id FROM manage_files_file 
            WHERE s3_key={self.param} AND owner_id={self.param} AND is_deleted={self.param}
            LIMIT 1;
        """, (date_folder_key, user_id, False))
        date_folder_row = cursor.fetchone()
        if date_folder_row:
            parent = date_folder_row[0]
        else:
            cursor.execute(f"""
                INSERT INTO manage_files_file (name, owner_id, s3_key, parent_id, created_at, size_gb, is_deleted)
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP, 0, {self.param})
                RETURNING id;
            """, (today, user_id, date_folder_key, parent, False))
            parent =  cursor.fetchone()[0]
        self.provide_permission(cursor, org_id, parent, user_id)

        # 10. Insert file under date folder
        signed_url = self.generate_presigned_url(s3, file_key)
        utc = pytz.utc
        signed_url_expires_at = datetime.now(utc) + timedelta(seconds=86400)
        cursor.execute(f"""
            INSERT INTO manage_files_file (name, owner_id, s3_key, parent_id, created_at, size_gb, is_deleted, signed_url, signed_url_expires_at)
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP, {self.param}, {self.param}, {self.param}, {self.param})
            RETURNING id;
        """, (filename, user_id, file_key, parent, size_gb, False, signed_url, signed_url_expires_at))
        self.logger.info(f"✅ Uploaded to {file_key}")
        file_id = cursor.fetchone()[0]
        self.provide_permission(cursor, org_id, file_id, user_id)

        # 11. Insert a new FileStorageEvent record
        cursor.execute(f"""
            INSERT INTO manage_files_filestorageevent (
                file_id_id, file_name, user_id, size_gb, start_time
            ) VALUES ({self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP);
        """, (file_id, filename, user_id, size_gb))

        
        return file_id, signed_url

    def handle_customer_message_whatsapp(self, msg_data):
        try:
            recipient_id = msg_data['recipient_id']
            message_type = msg_data['msg_type']
            message_body = message_body_copy = msg_data['message_body']
            phone_number_id = msg_data['phone_number_id']
            file_id = None

            with self.get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT id, owner_id, login_credentials FROM manage_platform_platform WHERE login_id={self.param}", (phone_number_id,))
                platform_row = cursor.fetchone()
                if not platform_row:
                    self.logger.warning("Platform not found for phone_number_id: %s", phone_number_id)
                    return
                platform_id, owner_id, login_credentials = platform_row

                signed_url = None
                if message_type != "text":
                    message_body_copy = message_body_copy.get("caption")
                    cursor.execute(f"SELECT user_id from manage_users_enterpriseprofile where user_id={self.param}", (owner_id,))
                    enterprise_profile = cursor.fetchone()
                    if not enterprise_profile:
                        self.logger.warning("Enterprise profile not found for owner_id: %s", owner_id)
                        raise Exception("User not registered as enterprise")
                    owner_user_id = enterprise_profile[0]
                    cursor.execute(f"SELECT email from manage_users_customuser where id={self.param}", (owner_user_id,))
                    owner_user_profile = cursor.fetchone()
                    if not owner_user_profile:
                        raise Exception("User not found in main user profile")
                    owner_email = owner_user_profile[0]
                    with self.download_from_provider(message_body.get("media_id"), login_credentials) as file_data:
                        media_file_name = message_body.get("caption")
                        if message_type in ("image/jpeg", "image/png"):
                            media_file_name = message_body.get("caption") + "." + message_type.split('/')[-1]
                        file_id, signed_url = self.save_media_file_to_s3_raw_sql(conn, owner_email, recipient_id, media_file_name, file_data)

                cursor.execute(f"SELECT id, owner_id FROM manage_organization_organization WHERE owner_id={self.param}", (owner_id,))
                org_row = cursor.fetchone()
                if not org_row:
                    self.logger.warning("Organization not found for owner_id: %s", owner_id)
                    return
                organization_id, org_owner_id = org_row

                contact_id, contact_name = None, None
                cursor.execute(f"SELECT id, name FROM manage_contact_contact WHERE phone={self.param} AND organization_id={self.param}", (recipient_id, organization_id))
                contact_row = cursor.fetchone()
                if contact_row:
                    contact_id, contact_name = contact_row
                else:
                    cursor.execute(
                        f"INSERT INTO manage_contact_contact (phone, name, organization_id, created_by_id, platform_name, created_at, updated_at) VALUES ({self.param}, '', {self.param}, {self.param}, {self.param}, {self.param}, {self.param}) RETURNING id, name",
                        (recipient_id, organization_id, org_owner_id, 'whatsapp', datetime.now(), datetime.now())
                    )
                    contact_id, contact_name = cursor.fetchone()

                is_conversation_new = True
                cursor.execute(f"""
                    SELECT id FROM manage_conversation_conversation
                    WHERE contact_id={self.param} AND platform_id={self.param} AND organization_id={self.param} AND status IN ('new', 'active')
                    ORDER BY created_at DESC LIMIT 1
                """, (contact_id, platform_id, organization_id))
                conv_row = cursor.fetchone()
                if conv_row:
                    conversation_id = conv_row[0]
                    is_conversation_new = False
                else:
                    cursor.execute(f"""
                        INSERT INTO manage_conversation_conversation (contact_id, platform_id, organization_id, open_by, status, created_at, updated_at)
                        VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}) RETURNING id
                    """, (contact_id, platform_id, organization_id, 'customer', 'new', datetime.now(), datetime.now()))
                    conversation_id = cursor.fetchone()[0]

                cursor.execute(f"""
                    INSERT INTO manage_conversation_incomingmessage (conversation_id, contact_id, platform_id, organization_id, message_body, message_type, status_details, status, received_time, created_at)
                    VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, 'unread', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id, received_time, status, status_details
                """, (conversation_id, contact_id, platform_id, organization_id, message_body if message_type=="text" else message_body.get("caption"), message_type, file_id))
                msg_row = cursor.fetchone()
                payload = {
                    'id': contact_id,
                    'conversation_id': conversation_id,
                    'received_time': msg_row[1].isoformat() if not self.use_sqlite else msg_row[1],
                    'message_type': message_type,
                    'message_body': message_body_copy,
                    'status': msg_row[2],
                    'status_details': msg_row[3],
                    'type': 'customer',
                    'msg_from_type': 'CUSTOMER',
                    'organization_id': organization_id,
                    'customer_name': contact_name,
                    'is_conversation_new': is_conversation_new,
                    'media_url': signed_url
                }
                self.logger.info("New customer message saved for conversation_id: %s", conversation_id)
                self.sio.emit("whatsapp_chat", payload)
        except Exception as e:
            self.logger.error("Error in handle_customer_message_whatsapp: %s", e, exc_info=True)

    def handle_org_message_whatsapp(self, msg_data):
        try:
            message_id = msg_data['message_id']
            message_status = msg_data['message_status']
            error_details = msg_data.get("error_details", None)
            with self.get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT id, conversation_id, organization_id FROM manage_conversation_usermessage WHERE messageid={self.param}", (message_id,))
                row = cursor.fetchone()
                if row:
                    user_message_id, conversation_id, organization_id = row
                    if error_details:
                        cursor.execute(f"""
                            UPDATE manage_conversation_usermessage SET status={self.param}, status_details={self.param} WHERE id={self.param}
                        """, (message_status, json.dumps(error_details), user_message_id))
                    else:
                        cursor.execute(f"""
                            UPDATE manage_conversation_usermessage SET status={self.param} WHERE id={self.param}
                        """, (message_status, user_message_id))

                    cursor.execute(f"""
                        UPDATE manage_conversation_incomingmessage SET status='responded' WHERE conversation_id={self.param}
                    """, (conversation_id,))

                    self.logger.info("Updated message status for user_message_id: %s", user_message_id)

                    self.sio.emit("whatsapp_chat", {
                        "conversation_id": conversation_id,
                        "msg_from_type": "ORG",
                        'organization_id': organization_id,
                    })
        except Exception as e:
            self.logger.error("Error in handle_org_message_whatsapp: %s", e, exc_info=True)


    @staticmethod
    def get_messenger_user_profile(psid, page_access_token):
        url = f"https://graph.facebook.com/v18.0/{psid}"
        params = {
            "fields": "first_name,last_name,profile_pic",
            "access_token": page_access_token
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json()  # {first_name, last_name, profile_pic}
        else:
            return {}

    def handle_customer_message_messenger(self, message):
        try:
            page_owner_id=message["page_owner_id"]
            sender_id=message["sender_id"]['id']
            message_status=message["message_status"]
            msg=message["msg"]
            message_type=message["msg_type"]
            timestamp=message["timestamp"]
            with self.get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT id, owner_id, login_credentials FROM manage_platform_platform WHERE login_id={self.param}", (page_owner_id,))
                platform_row = cursor.fetchone()
                if not platform_row:
                    self.logger.warning("Platform not found for phone_number_id: %s", page_owner_id)
                    return
                platform_id, owner_id, login_credentials = platform_row
                
                cursor.execute(f"SELECT id, owner_id FROM manage_organization_organization WHERE owner_id={self.param}", (owner_id,))
                org_row = cursor.fetchone()
                if not org_row:
                    self.logger.warning("Organization not found for owner_id: %s", owner_id)
                    return
                organization_id, org_owner_id = org_row
                contact_id, contact_name = None, None
                expires_at = int(time.time() * 1000) + 24 * 60 * 60 * 1000
                current_ms = int(time.time() * 1000)
                cursor.execute(f"SELECT id, name, image_expires_at FROM manage_contact_contact WHERE phone={self.param} AND organization_id={self.param}", (sender_id, organization_id))
                contact_row = cursor.fetchone()
                if contact_row:
                    contact_id, contact_name, image_expires_at = contact_row
                    # Check if image_expires_at is null or expired
                    if image_expires_at is None or int(image_expires_at) < current_ms:
                        # Refresh profile
                        profile = WhatsAppKafkaConsumer.get_messenger_user_profile(sender_id, login_credentials)
                        sender_name = profile.get("first_name")
                        profile_pic_url = profile.get("profile_pic")
                
                        # Update contact with new image and expiry time
                        cursor.execute(
                            f"""UPDATE manage_contact_contact
                                SET image={self.param}, image_expires_at={self.param}, name={self.param}, updated_at={self.param}
                                WHERE id={self.param}""",
                            (profile_pic_url, expires_at, sender_name, datetime.now(), contact_id)
                        )
                else:
                    profile = WhatsAppKafkaConsumer.get_messenger_user_profile(sender_id, login_credentials)
                    sender_name = profile.get("first_name")
                    profile_pic_url = profile.get("profile_pic")
                    cursor.execute(
                        f"INSERT INTO manage_contact_contact (phone, name, image, image_expires_at, organization_id, created_by_id, platform_name, created_at, updated_at) VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}) RETURNING id, name",
                        (sender_id, sender_name, profile_pic_url, expires_at, organization_id, org_owner_id, 'messenger', datetime.now(), datetime.now())
                    )
                    contact_id, contact_name = cursor.fetchone()
                is_conversation_new = True
                cursor.execute(f"""
                    SELECT id FROM manage_conversation_conversation
                    WHERE contact_id={self.param} AND platform_id={self.param} AND organization_id={self.param} AND status IN ('new', 'active')
                    ORDER BY created_at DESC LIMIT 1
                """, (contact_id, platform_id, organization_id))
                conv_row = cursor.fetchone()
                if conv_row:
                    conversation_id = conv_row[0]
                    is_conversation_new = False
                else:
                    cursor.execute(f"""
                        INSERT INTO manage_conversation_conversation (contact_id, platform_id, organization_id, open_by, status, created_at, updated_at)
                        VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}) RETURNING id
                    """, (contact_id, platform_id, organization_id, 'customer', 'new', datetime.now(), datetime.now()))
                    conversation_id = cursor.fetchone()[0]
                cursor.execute(f"""
                    INSERT INTO manage_conversation_incomingmessage (conversation_id, contact_id, platform_id, organization_id, message_body, message_type, status_details, status, received_time, created_at)
                    VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, 'unread', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id, received_time, status, status_details
                """, (conversation_id, contact_id, platform_id, organization_id, msg, message_type, None))
                msg_row = cursor.fetchone()
                payload = {
                    'id': contact_id,
                    'conversation_id': conversation_id,
                    'received_time': msg_row[1].isoformat() if not self.use_sqlite else msg_row[1],
                    'message_type': message_type,
                    'message_body': msg,
                    'status': msg_row[2],
                    'status_details': msg_row[3],
                    'type': 'customer',
                    'msg_from_type': 'CUSTOMER',
                    'organization_id': organization_id,
                    'customer_name': contact_name,
                    'is_conversation_new': is_conversation_new
                }
                self.logger.info("New customer message saved for conversation_id: %s", conversation_id)
                self.sio.emit("whatsapp_chat", payload)
        except Exception as e:
            self.logger.error("Error in handle_customer_message_whatsapp: %s", e, exc_info=True)

    def handle_org_message_messenger(self, message):
        try:
            page_owner_id=message["page_owner_id"]
            sender_id=message["sender_id"]['id']
            message_status=message["message_status"]
            timestamp=message["timestamp"]
            with self.get_conn() as conn:
                # Step 1: Get conversation and organization based on sender_id and page_owner_id
                cursor = conn.cursor()
                cursor.execute(f"SELECT id, owner_id, login_credentials FROM manage_platform_platform WHERE login_id={self.param}", (page_owner_id,))
                platform_row = cursor.fetchone()
                if not platform_row:
                    self.logger.warning("Platform not found for phone_number_id: %s", page_owner_id)
                    return
                platform_id, owner_id, login_credentials = platform_row
                
                cursor.execute(f"SELECT id, owner_id FROM manage_organization_organization WHERE owner_id={self.param}", (owner_id,))
                org_row = cursor.fetchone()
                if not org_row:
                    self.logger.warning("Organization not found for owner_id: %s", owner_id)
                    return
                organization_id, org_owner_id = org_row

                contact_id, contact_name = None, None
                cursor.execute(f"SELECT id, name FROM manage_contact_contact WHERE phone={self.param} AND organization_id={self.param}", (sender_id, organization_id))
                contact_row = cursor.fetchone()
                if contact_row:
                    contact_id, contact_name = contact_row
                    cursor.execute(f"""
                        SELECT id FROM manage_conversation_conversation 
                        WHERE platform_id={self.param} AND contact_id={self.param} 
                        AND status='active'
                    """, (platform_id, contact_id))
                    convo = cursor.fetchone()
                
                    if convo:
                        conversation_id = convo[0]
                        # Step 2: Update user messages for this conversation with lower message IDs
                        cursor.execute(f"""
                            UPDATE manage_conversation_usermessage
                            SET status={self.param} 
                            WHERE conversation_id={self.param} AND messageid~'^[0-9]+$' AND CAST(messageid AS BIGINT)<={self.param}
                        """, (message_status, conversation_id, timestamp))
    
                        # Step 3: Mark the incoming message as responded
                        cursor.execute(f"""
                            UPDATE manage_conversation_incomingmessage SET status='responded' WHERE conversation_id={self.param}
                        """, (conversation_id,))
    
                        self.logger.info("Messenger | Updated message status for conversation_id: %s", conversation_id)
    
                        self.sio.emit("whatsapp_chat", {
                            "conversation_id": conversation_id,
                            "msg_from_type": "ORG",
                            'organization_id': organization_id,
                        })
                    else:
                        self.logger.info("Messenger | Active conversation not found")
                else:
                    self.logger.info("Messenger | User not found in contact")
        except Exception as e:
            self.logger.error("Error in handle_org_message_messenger: %s", e, exc_info=True)


    
    def handle_website_chatwidget_messages(self, data):
        try:
            print("Received web chat message:", data)
            organization_id = data.get('organization_id', None)
            user_uuid_for_session = data.get('user', None)
            message_type = 'text'
            message_body = data.get('data')
            helper_message = "Thank you for reaching us. Please wait whie we are looking for a best dedicated engineer to help with your query"
            if not organization_id:
                self.sio.emit("website_chatwidget_messages_back_to_front", {
                    "message": "Warning: We found you are spoofing :)",
                    "user": data.get("user")
                })
            with self.get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT id FROM manage_platform_platform WHERE platform_name={self.param} AND organization_id={self.param}", ('webchat', organization_id))
                platform_row = cursor.fetchone()
                if not platform_row:
                    self.logger.warning("Platform not found for organization_id: %s", organization_id)
                    return
                platform_id = platform_row[0]

                # 1. Get Platform details
                cursor.execute(f"SELECT owner_id FROM manage_organization_organization WHERE id={self.param}", (organization_id,))
                org_row = cursor.fetchone()
                if not org_row:
                    self.logger.warning("Organization not found for organization_id: %s", organization_id)
                    return
                org_owner_id = org_row[0]

                # 2. Get contact details
                contact_id, contact_name = None, None
                cursor.execute(f"SELECT id, name FROM manage_contact_contact WHERE phone={self.param} AND organization_id={self.param} AND platform_name={self.param}", (user_uuid_for_session, organization_id, 'webchat'))
                contact_row = cursor.fetchone()
                if contact_row:
                    contact_id, contact_name = contact_row
                else:
                    cursor.execute(
                        f"INSERT INTO manage_contact_contact (phone, name, organization_id, created_by_id, platform_name, created_at, updated_at) VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}) RETURNING id, name",
                        (user_uuid_for_session, user_uuid_for_session, organization_id, org_owner_id, 'webchat', datetime.now(), datetime.now())
                    )
                    contact_id, contact_name = cursor.fetchone()
                
                is_conversation_new = True
                #3. Start new / get existing conversation
                cursor.execute(f"""
                    SELECT id FROM manage_conversation_conversation
                    WHERE contact_id={self.param} AND platform_id={self.param} AND organization_id={self.param} AND status IN ('new', 'active')
                    ORDER BY created_at DESC LIMIT 1
                """, (contact_id, platform_id, organization_id))
                conv_row = cursor.fetchone()
                if conv_row:
                    is_conversation_new = False
                    conversation_id = conv_row[0]
                else:
                    cursor.execute(f"""
                        INSERT INTO manage_conversation_conversation (contact_id, platform_id, organization_id, open_by, status, created_at, updated_at)
                        VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}) RETURNING id
                    """, (contact_id, platform_id, organization_id, 'customer', 'new', datetime.now(), datetime.now()))
                    conversation_id = cursor.fetchone()[0]
                
                # 4. Insert incoming message
                cursor.execute(f"""
                    INSERT INTO manage_conversation_incomingmessage (conversation_id, contact_id, platform_id, organization_id, message_body, message_type, status, received_time, created_at)
                    VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, 'unread', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id, received_time, status
                """, (conversation_id, contact_id, platform_id, organization_id, message_body, message_type))
                msg_row = cursor.fetchone()
                
                payload_main_ui_client = {
                    'id': contact_id,
                    'conversation_id': conversation_id,
                    'received_time': msg_row[1].isoformat() if not self.use_sqlite else msg_row[1],
                    'message_type': message_type,
                    'message_body': message_body,
                    'status': msg_row[2],
                    'status_details': None,
                    'type': 'customer',
                    'msg_from_type': 'CUSTOMER',
                    'customer_name': contact_name,
                    'organization_id': organization_id,
                    'is_conversation_new': is_conversation_new
                }

                payload_chat_widget_client = {
                    "message": helper_message if is_conversation_new else None,
                    "target_user": user_uuid_for_session
                }
                self.logger.info("Webchat | New customer message saved for conversation_id: %s", conversation_id)

                self.sio.emit("whatsapp_chat", payload_main_ui_client)
                self.sio.emit("website_chatwidget_messages_back_to_front", payload_chat_widget_client)
        except Exception as e:
            self.logger.error("Error in handle_website_chatwidget_messages: %s", e, exc_info=True)

    def consume(self):
        config = self.read_config()
        config['group.id'] = self.group_id
        config['auto.offset.reset'] = 'earliest'
        consumer = ConfluentConsumer(config)
        consumer.subscribe([self.topic])
        time.sleep(60) # Waiting for connection to be established with broker
        self.logger.info("Started Kafka consumer, subscribed to topic: %s", self.topic)

        try:
            while True:
                msg = consumer.poll(timeout=1.0)
                if msg is None:
                    time.sleep(1)
                    continue
                if msg and msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        self.logger.debug("End of partition: %s", msg.error())
                    else:
                        self.logger.error("Kafka consumer error: %s", msg.error())
                    continue
                try:
                    message_value = json.loads(msg.value().decode('utf-8'))
                    self.logger.info("Received Kafka message: %s", message_value)
                    self.process_message(message_value)
                except Exception as e:
                    self.logger.error("Failed to process message: %s", e, exc_info=True)
        finally:
            self.logger.info("Stopping Kafka consumer...")
            consumer.close()
    
    def devlmode(self):
        try:
            while True:
                time.sleep(60)
        finally:
            self.logger.info("Closing long running main thread")



if __name__ == "__main__":
    if os.environ["PRODUCTION"] == '1':
        WhatsAppKafkaConsumer().consume()
    else:
        WhatsAppKafkaConsumer().devlmode()
