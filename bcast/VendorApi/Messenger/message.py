
import requests
from VendorApi.Messenger import api
from VendorApi.Messenger import SendException


class Message:
    def __init__(self, phone_number_id, token):
        self.phone_number_id = phone_number_id
        self.token = token
        self.send_url = api.send

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def send_message(self, recipient_id, message_body):
        pass


class TextMessage(Message):
    MSG_TYPE = "text"
    def __init__(self, phone_number_id, token):
        super().__init__(phone_number_id, token)

    def send_message(self, recipient_id, message_body):
        payload = {
            "message": { self.MSG_TYPE: message_body },
            "recipient": { "id": recipient_id }
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
