import base64
import json
import requests
import mimetypes

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from VendorApi.Messenger import SendException
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from manage_platform.models import GmailAccount

GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GmailMessage:
    def __init__(self, platform):
        self.platform = platform
        self.gmail_account = platform.gmail_account  # OneToOne relation
        self.client_id = settings.GOOGLE_CLIENT_ID
        self.client_secret = settings.GOOGLE_CLIENT_SECRET
        self.sender_email = self.gmail_account.email_address
        self.send_url = f"https://gmail.googleapis.com/gmail/v1/users/{self.sender_email}/messages/send"

        # Ensure valid access token
        self.access_token = self.get_valid_access_token()

    def get_valid_access_token(self):
        if self.gmail_account.is_token_expired:
            self.refresh_access_token()
        return self.gmail_account.access_token

    def refresh_access_token(self):
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.gmail_account.refresh_token,
            "grant_type": "refresh_token",
        }
        response = requests.post(GMAIL_TOKEN_URL, data=data)
        if response.status_code not in range(200, 299):
            raise SendException(f"Gmail token refresh failed: {response.text}")

        token_data = response.json()
        access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in", 3600)  # fallback 1 hour
        expiry_time = timezone.now() + timedelta(seconds=expires_in)

        # Update DB
        self.gmail_account.access_token = access_token
        self.gmail_account.token_expiry = expiry_time
        self.gmail_account.save(update_fields=["access_token", "token_expiry"])

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def send_message(self, to_email, subject, message_body, thread_id=None, in_reply_to=None):
        message = MIMEText(message_body)
        message["to"] = to_email
        message["subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
            message["References"] = in_reply_to    
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        body = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        response = requests.post(self.send_url, headers=self.headers, json=body)
        if response.status_code not in range(200, 299):
            raise SendException(f"Gmail text send failed: {response.text}")    
        # ✅ Return parsed message ID and thread ID
        result = response.json()
        return {
            "messageid": result.get("id"),
            "thread_id": result.get("threadId"),
            "raw_response": result
        }


    def send_message_with_attachment(self, to_email, subject, message_body, file_data: bytes, filename: str, thread_id=None, in_reply_to=None):
        # Auto-detect MIME type
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = "application/octet-stream"
        message = MIMEMultipart()
        message["to"] = to_email
        #message["from"] = self.sender_email
        message["subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
            message["References"] = in_reply_to
        message.attach(MIMEText(message_body, "plain"))
        maintype, subtype = mime_type.split("/")
        attachment = MIMEApplication(file_data, _subtype=subtype)
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        message.attach(attachment)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        body = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        response = requests.post(self.send_url, headers=self.headers, json=body)
        if response.status_code not in range(200, 299):
            raise SendException(f"Gmail attachment send failed: {response.text}")
        # ✅ Return parsed message ID and thread ID
        result = response.json()
        return {
            "messageid": result.get("id"),
            "thread_id": result.get("threadId"),
            "raw_response": result
        }

