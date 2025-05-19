import json

import requests
from VendorApi.Webchat import api
from VendorApi.Webchat import SendException


MAX_TIMEOUT = 120 # 120 seconds

class Message:
    def __init__(self, token):
        self.token = token
        self.send_url = api.send

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def send_message(self, target_user, message):
        pass


class TextMessage(Message):
    def __init__(self, token):
        super().__init__(token)

    def send_message(self, target_user, message):
        payload = {
            "target_user": target_user,
            "message": message
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
