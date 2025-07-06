import os
import base64
import json
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from django.utils.timezone import make_aware
from django.utils import timezone
from google.auth.transport.requests import Request
from dotenv import load_dotenv
from decouple import config

from django.conf import settings

load_dotenv()


def get_gmail_service(account):
    creds = Credentials(
        token=account.access_token,
        refresh_token=account.refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        account.access_token = creds.token
        # Google sets token expiry duration on creds.expiry
        if creds.expiry:
            account.token_expiry = creds.expiry
        else:
            account.token_expiry = timezone.now() + timedelta(seconds=3600)
        account.save(update_fields=["access_token", "token_expiry"])
    service = build('gmail', 'v1', credentials=creds)
    return service, creds


def watch_gmail(account):
    service, creds = get_gmail_service(account)
    body = {
        "topicName": config('PUB_SUB_GMAIL_TOPIC'),
        "labelIds": ["UNREAD", "IMPORTANT", "CATEGORY_PERSONAL", "INBOX"]
    }
    result = service.users().watch(userId='me', body=body).execute()
    print("Gmail watch response:", result)
    # Extract expiration from watch response
    expiration_ts = int(result.get("expiration", 0))  # in milliseconds
    expiration_dt = make_aware(datetime.utcfromtimestamp(expiration_ts / 1000)) if expiration_ts else None
    # Update GmailAccount
    account.history_id = result['historyId']
    account.last_watch_time = make_aware(datetime.utcnow())
    account.watch_expiry = expiration_dt
    account.access_token = creds.token
    account.save(update_fields=["history_id", "last_watch_time", "watch_expiry", "access_token"])
    return result


def handle_full_sync_unread(account, service):
    """
    Handles full sync by fetching only unread messages,
    and updates the account's history_id to the latest one.
    """
    print(f"Doing unread sync for {account.email}")

    try:
        response = service.users().messages().list(
            userId='me',
            q='is:unread',
            maxResults=100  # or None to get all unread messages
        ).execute()

        messages = response.get('messages', [])
        if not messages:
            print("No unread messages found.")
            return

        for message in messages:
            msg_detail = service.users().messages().get(
                userId='me',
                id=message['id'],
                format='full'  # or 'metadata' if you just need headers
            ).execute()

            # Handle the unread message here (e.g., extract content, process sender/subject)
            print(f"Unread message from: {msg_detail['payload'].get('headers', [])}")

        # Update history ID from the most recent unread message
        latest_msg = service.users().messages().get(
            userId='me',
            id=messages[0]['id'],
            format='metadata'
        ).execute()

        new_history_id = latest_msg.get('historyId')
        if new_history_id:
            account.history_id = new_history_id
            account.save()
            print(f"Updated history ID to {new_history_id}")

    except HttpError as error:
        print(f"Failed to perform unread sync: {error}")
        raise


def poll_history(account):
    service, creds = get_gmail_service(account)
    result = []
    result = service.users().history().list(
        userId='me',
        startHistoryId=account.history_id,
        historyTypes=['messageAdded']
    ).execute()


    if result and 'history' in result:
        for history in result['history']:
            for msg in history.get('messages', []):
                try:
                    msg_detail = service.users().messages().get(
                        userId='me', id=msg['id']).execute()
                    snippet = msg_detail.get("snippet", "")
                    print("Raw message ", msg_detail)
                    print(f"[{account.email_address}] New message: {snippet}")
                except HttpError as error:
                    # Skip 404 error since reply to message changes the id
                    pass
    account.history_id = result.get('historyId', account.history_id)
    account.access_token = creds.token
    #account.token_expiry = make_aware(creds.expiry)
    account.save()