import time
import json

import requests
from VendorApi.Whatsapp import api
from VendorApi.Whatsapp import ( SendException, WebHookException )


MAX_TIMEOUT = 120 # 120 seconds

class Message:
    def __init__(self, phone_number_id, token):
        self.phone_number_id = phone_number_id
        self.token = token
        self.send_url = api.send.format(phone_number_id=self.phone_number_id)
        self.upload_url = api.upload.format(phone_number_id=self.phone_number_id)

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def send_message(self, recipient_id, message_body):
        pass


class TextMessage(Message):
    def __init__(self, phone_number_id, token, client_application="schedule"):
        super().__init__(phone_number_id, token)
        self.client_application = client_application

    def send_message(self, recipient_id, message_body):
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "text",
            "text": {"body": message_body}
        }
        response = requests.post(
            self.send_url,
            json=payload,
            headers=self.headers
        )
        if response.status_code not in range(200, 299):
            error_response = response.json()
            raise SendException(error_response.get("error", {}).get("message", "Unknown Error - Please engage engineering."))
        return response


class TemplateMessage(Message):
    def __init__(self, waba_id, phone_number_id, token, client_application="schedule"):
        super().__init__(phone_number_id, token)
        self.template_url = api.get_templates.format(whatsapp_business_id=waba_id)
        self.client_application = client_application

    def get_templates(self):
        response = requests.get(
            self.template_url,
            headers=self.headers
        )
        if response.status_code not in range(200, 299):
            error_response = response.json()
            raise SendException(error_response.get("error", {}).get("message", "Unknown Error - Please engage engineering."))
        return response
    
    def template_payload_body(self, parameter_body):
        return {
            "components": [
                {
                    "type": "body",
                    "parameters": parameter_body
                }
            ]
        }

    
    def send_message(self, recipient_id, message_body, template, file_obj=None, mime_type=None):
        template_obj = template
        if isinstance(template_obj, str):
            template_obj = json.loads(template)
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "template",
            "template": { "name": template_obj["name"], "language": { "code": template_obj["language"] } }
        }
        # Default payload
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "template",
            "template": {
                "name": template_obj["name"],
                "language": {"code": template_obj["language"]},
                "components": []
            }
        }
        # --- Handle HEADER with DOCUMENT format ---
        header_component = next((c for c in template_obj.get("components", []) if c.get("type") == "HEADER"), None)
        if header_component and header_component.get("format") == "DOCUMENT" and file_obj:
            media_id = MediaMessage(self.phone_number_id, self.token).upload_media(file_obj, mime_type)

            media_payload = {
                "id": media_id,
                "filename": file_obj.name
            }

            payload["template"]["components"].append({
                "type": "HEADER",
                "parameters": [
                    {
                        "type": "document",
                        "document": media_payload
                    }
                ]
            })
        # --- Handle BODY parameters ---
        if message_body not in [None, 'TEMPLATE']:
            #payload = {
            #    "messaging_product": "whatsapp",
            #    "to": recipient_id,
            #    "type": "template",
            #    "template": { "name": template_obj["name"], "language": { "code": template_obj["language"] }, **self.template_payload_body(message_body)}
            #}
            payload["template"]["components"].append({
                "type": "BODY",
                "parameters": message_body
            })
        
        response = requests.post(
            self.send_url,
            json=payload,
            headers=self.headers
        )
        if response.status_code not in range(200, 299):
            error_response = response.json()
            raise SendException(error_response.get("error", {}).get("message", "Unknown Error - Please engage engineering."))
        return response


import requests

class MediaMessage(Message):
    def __init__(self, phone_number_id, token):
        super().__init__(phone_number_id, token)

    def upload_media(self, file_obj, mime_type):
        """Upload media file to WhatsApp Cloud API and return media_id"""
        files = {
            "file": (file_obj.name, file_obj, mime_type),
        }
        data = {
            "messaging_product": "whatsapp"
        }        
        response = requests.post(self.upload_url, headers=self.headers, files=files, data=data)
        response.raise_for_status()
        return response.json().get("id")

    def send_media_message(self, recipient, file_obj, media_type, mime_type, caption=None):
        """Send a media message (image/audio/video/document)"""
        media_id = self.upload_media(file_obj, mime_type)
        media_payload = {
            "id": media_id
        }
        # Add filename only for documents
        if media_type == "document":
            media_payload["filename"] = file_obj.name
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": media_type,
            media_type: media_payload
        }
        if caption and media_type in ["image", "video", "document"]:
            payload[media_type]["caption"] = caption
        response = requests.post(self.send_url, headers=self.headers, json=payload)
        if response.status_code not in range(200, 299):
            error_response = response.json()
            raise SendException(error_response.get("error", {}).get("message", "Unknown Error - Please engage engineering."))
        return response
