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
        self.get_template_url = api.get_templates.format(whatsapp_business_id=waba_id)
        self.client_application = client_application

    def get_templates(self):
        response = requests.get(
            self.get_template_url,
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

    
    def send_message(self, recipient_id, message_body, template):
        template_obj = template
        if isinstance(template_obj, str):
            template_obj = json.loads(template)
        payload = {}
        if message_body in [None, 'TEMPLATE']:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient_id,
                "type": "template",
                "template": { "name": template_obj["name"], "language": { "code": template_obj["language"] } }
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient_id,
                "type": "template",
                "template": { "name": template_obj["name"], "language": { "code": template_obj["language"] }, **self.template_payload_body(message_body)}
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
