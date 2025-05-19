import time
import os
import json
import logging
from django.utils.timezone import now
from django.db import transaction
from django.conf import settings

from celery import shared_task

from manage_conversation.models import Conversation, UserMessage
from manage_contact.models import Contact
from manage_platform.models import Platform
from .models import ScheduledMessage, PlatformLog

from VendorApi.Whatsapp.message import TextMessage, TemplateMessage

logger = logging.getLogger(__name__)

MSG_SENT = ['sent', 'accepted']

def substitute_placeholders(phone_number, message_content, datasource, template):
    try:
        substitutions = {}
        if not datasource:
            return substitutions
        for placeholder, config in datasource.items():                
            if config['type'] == 'excel':
                excel_data = config.get('data', [])
                for row in excel_data:
                    excel_phone_number = str(row.get('Phone'))
                    if excel_phone_number == phone_number:
                        row['Phone'] = Contact.objects.get(phone=excel_phone_number).name
                        if template:
                            headers = [header for header in row.keys() if header != 'Phone']
                            substitutions[excel_phone_number] = [
                                {"type": "text", "parameter_name": str(col), "text": str(row.get(col))}
                                for col in headers
                            ]
                        else:
                            substitutions[excel_phone_number] = message_content.format(**row)
        return substitutions
    except Exception as fetch_exception:
        raise fetch_exception

def send_message(platform_id, recipient_id, message_body, template=None):
    try:
        platform = Platform.objects.get(id=platform_id)
        recipient_phone_number = Contact.objects.get(id=recipient_id).phone

        if platform.platform_name.startswith('whatsapp'):
            print(
                "Message Sent!!\n",
                "Platform : ", platform.platform_name, "\n",
                "Login Id : ", platform.login_id, "\n", 
                "From Key : ", platform.login_credentials, "\n",
                "Recipient : ", recipient_phone_number, "\n",
                "Message : ", message_body, "\n"
            )

            if not template:
                text_message = TextMessage(
                    phone_number_id=platform.login_id,
                    token=platform.login_credentials
                )
                response = text_message.send_message(recipient_phone_number, message_body)
                response = response.json()
                return response

            approved_templates = TemplateMessage(
                waba_id=platform.app_id,
                phone_number_id=platform.login_id,
                token=platform.login_credentials
            )
            response = approved_templates.send_message(recipient_phone_number, message_body, template)
            return response.json()
        else:
            raise ValueError("Unsupported platform")
    except Exception as e:
        raise RuntimeError(f"Failed to send message: {str(e)}")

import traceback

def process_recipient(recipient, message_content, scheduled_message):
    try:
        formatted_message = substitute_placeholders(
            recipient.phone,
            message_content,
            scheduled_message.datasource,
            scheduled_message.template
        )
        if not formatted_message.get(recipient.phone):
            # The phone number is not present in excel and skipping
            return

        platform = scheduled_message.platform
        organization = scheduled_message.organization

        robo_name = organization.robo_name
        robo_user = organization.owner

        conversation, _ = Conversation.objects.get_or_create(
            assigned_user=robo_user,
            organization=organization,
            platform=platform,
            contact=recipient,
            defaults={
                'open_by': robo_name,
                'closed_by': robo_user,
                'status': 'closed'
            }
        )

        response = send_message(
            platform_id=platform.id,
            recipient_id=recipient.id,
            message_body="TEMPLATE" if scheduled_message.template else formatted_message,
            template=scheduled_message.template
        )

        UserMessage.objects.create(
            conversation=conversation,
            organization=organization,
            platform=platform,
            user=robo_user,
            message_body="TEMPLATE" if scheduled_message.template else formatted_message,
            status='sent' if response['messages'][0].get('message_status') in MSG_SENT else 'failed',
            sent_time=now(),
            messageid=response['messages'][0].get('id'),
            template=format_template_messages(
                scheduled_message.template,
                {param['parameter_name']: param['text'] for param in formatted_message} if formatted_message[recipient.phone] else None
            ) if scheduled_message.template else formatted_message
        )

        log_platform_activity(
            org_id=organization.id,
            event_type='message_sent',
            status='success' if response['messages'][0].get('message_status') in MSG_SENT else 'failed',
            details={'message_id': scheduled_message.id, 'response': response},
            recipient_id=recipient,
            schedule_id=scheduled_message
        )

        return response['messages'][0].get('message_status') in MSG_SENT
    except Exception as e:
        traceback.print_exc()
        log_platform_activity(
            org_id=scheduled_message.organization_id,
            event_type='message_failed',
            status='failed',
            details={'error': str(e)},
            recipient_id=recipient,
            schedule_id=scheduled_message
        )
        return False

def update_message_status(scheduled_message, status, next_run=None):
    scheduled_message.status = status
    if next_run:
        scheduled_message.scheduled_time = next_run
    scheduled_message.save(update_fields=['status', 'scheduled_time'])

def log_platform_activity(org_id, event_type, status, details, recipient_id, schedule_id):
    PlatformLog.objects.create(
        organization_id=org_id,
        recipient=recipient_id,
        scheduled_message=schedule_id,
        status=status,
        log_message=details
    )

def get_recipients(scheduled_message):
    if scheduled_message.recipient_type == 'group':
        return Contact.objects.filter(groups__group_id=scheduled_message.recipient_id)
    return Contact.objects.filter(id=scheduled_message.recipient_id)

def format_template_messages(template, parameters_body):
    if not parameters_body:
        return json.dumps(template)
    template = json.loads(template)
    for component in template.get('components', []):
        for buffer in parameters_body.keys():
            try:
                parameter_index = component['text'].index(buffer)
                start_index = parameter_index - 2
                end_index = parameter_index + len(buffer) + 2
                component['text'] = component['text'].replace(component['text'][start_index:end_index], parameters_body[buffer])
            except (ValueError, KeyError):
                continue
    return json.dumps(template)


@shared_task(bind=True, queue='schedule_monitor_queue')
def process_campaign_schedule_message(self):
    try:
        while True:
            logger.info("Checking for scheduled messages")
            with transaction.atomic():
                # Lock rows to avoid race conditions in multi-worker setups
                scheduled_messages = (
                    ScheduledMessage.objects.select_for_update(skip_locked=True)
                    .select_related('user', 'organization', 'platform')
                    .filter(status='scheduled', scheduled_time__lte=now())
                )
                for scheduled_message in scheduled_messages:
                    try:
                        if scheduled_message.status != 'scheduled':
                            continue
                        # Immediately mark as in progress to prevent duplicate pickup
                        scheduled_message.status = 'in_progress'
                        scheduled_message.save(update_fields=['status'])
                        recipients = get_recipients(scheduled_message)
                        message_content = scheduled_message.template if scheduled_message.template else scheduled_message.message_body
                        successful_deliveries = sum(
                            process_recipient(recipient, message_content, scheduled_message) for recipient in recipients
                        )
                        if successful_deliveries == len(recipients):
                            next_run = scheduled_message.get_next_run_time() if scheduled_message.frequency > 0 else None
                            update_message_status(scheduled_message, 'scheduled' if next_run else 'completed', next_run)
                        else:
                            update_message_status(scheduled_message, 'failed')
                    except Exception as schedule_err:
                        update_message_status(scheduled_message, 'failed')
                        logger.error(f"Error processing message {scheduled_message.id}: {schedule_err}")
            time.sleep(8)
    finally:
        # Ensure lock is removed on exit
        if os.path.exists(settings.LOCK_FILE_CAMPAIGN):
            os.remove(settings.LOCK_FILE_CAMPAIGN)
