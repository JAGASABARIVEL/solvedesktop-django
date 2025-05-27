import os
import json
import traceback
import time
import logging
import sqlite3
import psycopg2
from contextlib import contextmanager
import datetime
from dateutil.relativedelta import relativedelta
from decouple import config

from VendorApi.Whatsapp.message import TextMessage, TemplateMessage


os.environ["PRODUCTION"] = config("PRODUCTION")
os.environ["SQLITE_DB"] = 'db.sqlite3'
os.environ["PG_DB"] = config("PG_DB")
os.environ["PG_HOST"] = config("PG_HOST")
os.environ["PG_PORT"] = config("PG_PORT")
os.environ["PG_USER"] = config("PG_USER")
os.environ["PG_PASSWORD"] = config("PG_PASSWORD")

CAMPAIGN_CLOSED_REASON = "Campaign"


class CampaignScheduleMonitor:
    def __init__(self):
        self.use_sqlite = os.getenv("PRODUCTION") == '0'
        self.db_driver = sqlite3 if self.use_sqlite else psycopg2
        self.db_file = os.getenv("SQLITE_DB", "dev.sqlite3")
        self.MSG_SENT = ["sent", "accepted", "delivered", "read"]

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
        finally:
            conn.close()

    @property
    def param(self):
        return '?' if self.use_sqlite else '%s'
    
    @staticmethod
    def calculate_next_run(frequency, current_time=None):
        current_time = current_time or datetime.datetime.now(datetime.timezone.utc)
        if frequency == -1:  # "NA"
            return None
        elif frequency == 0:  # "Daily"
            return current_time + datetime.timedelta(days=1)
        elif frequency == 1:  # "Weekly"
            return current_time + datetime.timedelta(weeks=1)
        elif frequency == 2:  # "Monthly"
            return current_time + relativedelta(months=1)
        elif frequency == 3:  # "Quarterly"
            return current_time + relativedelta(months=3)
        elif frequency == 4:  # "Half-Yearly"
            return current_time + relativedelta(months=6)
        elif frequency == 5:  # "Yearly"
            return current_time + relativedelta(years=1)
        else:
            return None

    def format_template_messages(self, template, parameters_body):
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
    
    def update_message_status(self, schedule_id, status, next_run=None):
        with self.get_conn() as conn:
            cursor = conn.cursor()
            if next_run:
                cursor.execute(
                    f"UPDATE manage_campaign_scheduledmessage SET status={self.param},scheduled_time={self.param} WHERE id={self.param}",
                    (status, next_run, schedule_id)
                )
            else:
                cursor.execute(
                    f"UPDATE manage_campaign_scheduledmessage SET status={self.param} WHERE id={self.param}",
                    (status, schedule_id)
                )

    def log_platform_activity(self, conn, org_id, event_type, status, details, recipient_id, schedule_id):
        import json
        details = json.dumps(details)
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO manage_campaign_platformlog
            (organization_id, recipient_id, scheduled_message_id, status, log_message, created_at)
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (org_id, recipient_id, schedule_id, status, details, datetime.datetime.now(datetime.timezone.utc))
        )

    def get_recipients(self, conn, recipient_type, recipient_id):
        cursor = conn.cursor()
        if recipient_type == 'group':
            cursor.execute(
                f"""
                SELECT c.id, c.name, c.phone
                FROM manage_contact_contact c
                JOIN manage_contact_groupmember g ON c.id=g.contact_id
                WHERE g.group_id={self.param}
                """,
                (recipient_id,)
            )
        else:
            cursor.execute(
                f"SELECT id, name, phone FROM manage_contact_contact WHERE id={self.param}",
                (recipient_id,)
            )
        return cursor.fetchall()

    def substitute_placeholders(self, conn, phone_number, message_content, datasource, template):
        substitutions = {}
        if not datasource:
            return substitutions
        cursor = conn.cursor()
        try:
            #datasource = json.loads(datasource)
            for placeholder, config in datasource.items():
                if config['type'] == 'excel':
                    excel_data = config.get('data', [])
                    for row in excel_data:
                        excel_phone_number = str(row.get('phone'))
                        if excel_phone_number == phone_number:
                            # Get contact name using raw SQL
                            cursor.execute(
                                f"SELECT name FROM manage_contact_contact WHERE phone={self.param}",
                                (excel_phone_number,)
                            )
                            result = cursor.fetchone()
                            contact_name = result[0] if result else excel_phone_number
                            row['phone'] = contact_name
                            if template:
                                headers = [header for header in row.keys() if header != 'phone']
                                substitutions[excel_phone_number] = [
                                    {
                                        "type": "text",
                                        "parameter_name": str(col),
                                        "text": str(row.get(col))
                                    }
                                    for col in headers
                                ]
                            else:
                                try:
                                    substitutions[excel_phone_number] = message_content.format(**row)
                                except KeyError as e:
                                    self.logger.warning(f"Missing key {e} in row for phone {excel_phone_number}")
                                    substitutions[excel_phone_number] = message_content  # fallback
            return substitutions
        except Exception as fetch_exception:
            self.logger.error("Error in substitute_placeholders", exc_info=True)
            raise fetch_exception

    def send_message(self, conn, platform_id, recipient_id, message_body, template=None):
        cursor = conn.cursor()
        try:
            # Fetch platform details
            cursor.execute(
                f"SELECT platform_name, login_id, login_credentials, app_id FROM manage_platform_platform WHERE id={self.param}",
                (platform_id,)
            )
            platform_row = cursor.fetchone()
            if not platform_row:
                raise ValueError(f"No platform found with id {platform_id}")
            platform_name, login_id, login_credentials, app_id = platform_row
            # Fetch recipient phone number
            cursor.execute(
                f"SELECT phone FROM manage_contact_contact WHERE id={self.param}",
                (recipient_id,)
            )
            contact_row = cursor.fetchone()
            if not contact_row:
                raise ValueError(f"No contact found with id {recipient_id}")
            recipient_phone_number = contact_row[0]
            if platform_name.startswith('whatsapp'):
                print(
                    "Message Sent!!\n",
                    "Platform : ", platform_name, "\n",
                    "Login Id : ", login_id, "\n", 
                    "From Key : ", login_credentials, "\n",
                    "Recipient : ", recipient_phone_number, "\n",
                    "Message : ", message_body, "\n"
                )
                if not template:
                    text_message = TextMessage(
                        phone_number_id=login_id,
                        token=login_credentials
                    )
                    response = text_message.send_message(recipient_phone_number, message_body)
                    return response.json()
                approved_templates = TemplateMessage(
                    waba_id=app_id,
                    phone_number_id=login_id,
                    token=login_credentials
                )
                response = approved_templates.send_message(recipient_phone_number, message_body, template)
                return response.json()
            else:
                raise ValueError("Unsupported platform")
        except Exception as e:
            self.logger.error(f"Failed to send message", exc_info=True)
            raise RuntimeError(f"Failed to send message: {str(e)}")

    def update_user_message_model(self, cursor, response=None, **kwargs):
        cursor.execute(
            f"""
            INSERT INTO manage_conversation_usermessage
            (conversation_id, organization_id, platform_id, user_id, message_body, status, sent_time, messageid, template, message_type)
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP, {self.param}, {self.param}, {self.param})
            """,
            (
                kwargs.get("conversation_id"),
                kwargs.get("organization").id,
                kwargs.get("platform").id,
                kwargs.get("robo_user"),
                "TEMPLATE" if kwargs.get("scheduled_message").template else str(kwargs.get("formatted_message")),
                'sent' if response and next(iter(response.get('messages')), {}).get('message_status') in self.MSG_SENT else 'failed',
                next(iter(response.get('messages')), {}).get('id') if response else None,
                str(self.format_template_messages(
                    kwargs.get("scheduled_message").template,
                    {param['parameter_name']: param['text'] for param in kwargs.get("formatted_message")[kwargs.get("recipient").phone]}
                    if kwargs.get("formatted_message").get(kwargs.get("recipient").phone) else None
                )) if kwargs.get("scheduled_message").template else str(kwargs.get("formatted_message")),
                "template"
            )
        )

    def process_recipient(self, conn, recipient, message_content, scheduled_message):
        try:
            formatted_message = self.substitute_placeholders(
                conn,
                recipient.phone,
                message_content,
                scheduled_message.datasource,
                scheduled_message.template
            )
            if formatted_message.get(recipient.phone, None) is None:
                return
            platform = scheduled_message.platform
            organization = scheduled_message.organization
            robo_name = None
            robo_user = None
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT id,username,email FROM manage_users_customuser 
                WHERE user_type='agent' AND id IN 
                (SELECT user_id FROM manage_users_enterpriseprofile 
                WHERE organization_id={self.param})
                """,
                (organization.id,)
            )
            agent_row = cursor.fetchone()
            robo_user = agent_row[0]
            robo_name = agent_row[1]
            conversation_id = -1
            cursor.execute(
                f"""
                INSERT INTO manage_conversation_conversation
                (assigned_user_id, organization_id, platform_id, contact_id, open_by, closed_by_id, closed_reason, status, created_at, updated_at)
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                (robo_user, organization.id, platform.id, recipient.id, robo_name, robo_user, CAMPAIGN_CLOSED_REASON, 'closed')
            )
            conversation_id = cursor.fetchone()[0]
            response = self.send_message(
                conn,
                platform_id=platform.id,
                recipient_id=recipient.id,
                message_body="TEMPLATE" if scheduled_message.template else formatted_message,
                template=scheduled_message.template
            )
            self.logger.info("response %s %s %s", response, formatted_message, scheduled_message.template)
            #cursor.execute(
            #    f"""
            #    INSERT INTO manage_conversation_usermessage
            #    (conversation_id, organization_id, platform_id, user_id, message_body, status, sent_time, messageid, template, message_type)
            #    VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, CURRENT_TIMESTAMP, {self.param}, {self.param}, {self.param})
            #    """,
            #    (
            #        conversation_id,
            #        organization.id,
            #        platform.id,
            #        robo_user,
            #        "TEMPLATE" if scheduled_message.template else str(formatted_message),
            #        'sent' if response['messages'][0].get('message_status') in self.MSG_SENT else 'failed',
            #        response['messages'][0].get('id'),
            #        str(self.format_template_messages(
            #            scheduled_message.template,
            #            {param['parameter_name']: param['text'] for param in formatted_message[recipient.phone]}
            #            if formatted_message.get(recipient.phone) else None
            #        )) if scheduled_message.template else str(formatted_message),
            #        "template"
            #    )
            #)
            self.update_user_message_model(
                cursor,
                response=response,
                conversation_id=conversation_id,
                organization=organization,
                platform=platform,
                robo_user=robo_user,
                scheduled_message=scheduled_message,
                formatted_message=formatted_message,
                recipient=recipient
            )
            self.log_platform_activity(
                conn,
                org_id=organization.id,
                event_type='message_sent',
                status='success' if response['messages'][0].get('message_status') in self.MSG_SENT else 'failed',
                details={'message_id': scheduled_message.id, 'response': response},
                recipient_id=recipient.id,
                schedule_id=scheduled_message.id
            )
            return response['messages'][0].get('message_status') in self.MSG_SENT
        except Exception as e:
            traceback.print_exc()
            self.update_user_message_model(
                cursor,
                conversation_id=conversation_id,
                organization=organization,
                platform=platform,
                robo_user=robo_user,
                scheduled_message=scheduled_message,
                formatted_message=formatted_message,
                recipient=recipient
            )
            self.log_platform_activity(
                conn,
                org_id=scheduled_message.organization_id,
                event_type='message_failed',
                status='failed',
                details={'error': str(e)},
                recipient_id=recipient.id,
                schedule_id=scheduled_message.id
            )
            return False

    def process_campaign_schedule_message(self):
        from types import SimpleNamespace
        try:
            self.logger.info("Checking for scheduled messages")
            with self.get_conn() as conn:
                cursor = conn.cursor()
                # Lock eligible scheduled messages
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                cursor.execute(f"""
                    SELECT id, frequency, template, message_body, recipient_type, recipient_id, 
                           platform_id, organization_id, datasource 
                    FROM manage_campaign_scheduledmessage 
                    WHERE status IN ('scheduled', 'scheduled_warning') AND scheduled_time<={self.param}
                """, (now_utc,))
                messages = cursor.fetchall()
                for msg in messages:
                    (
                        schedule_id, frequency, template, message_body, recipient_type, 
                        recipient_id, platform_id, organization_id, datasource
                    ) = msg
                    cursor.execute(f"""
                            SELECT id, owner_id 
                            FROM manage_organization_organization 
                            WHERE id={self.param}
                        """, (organization_id,))
                    organization = cursor.fetchone()
                    # Mark as in_progress immediately
                    cursor.execute(f"""
                        UPDATE manage_campaign_scheduledmessage 
                        SET status={self.param} 
                        WHERE id={self.param}
                    """, ('in_progress',schedule_id,))
                    conn.commit()
                    recipients = self.get_recipients(conn, recipient_type, recipient_id)
                    successful_deliveries = 0
                    for recipient in recipients:
                        recipient_obj = SimpleNamespace(id=recipient[0], phone=recipient[2])
                        scheduled_msg_obj = SimpleNamespace(
                            id=schedule_id,
                            frequency=frequency,
                            template=template,
                            message_body=message_body,
                            recipient_id=recipient_id,
                            recipient_type=recipient_type,
                            platform_id=platform_id,
                            organization_id=organization_id,
                            datasource=datasource,
                            platform=SimpleNamespace(id=platform_id),
                            organization=SimpleNamespace(id=organization[0], owner_id=organization[1])
                        )
                        status = self.process_recipient(conn, recipient_obj, template or message_body, scheduled_msg_obj)
                        successful_deliveries += 1 if status else 0
                    # Reschedule or complete/failed
                    if successful_deliveries == 0:
                        cursor.execute(f"""
                            UPDATE manage_campaign_scheduledmessage 
                            SET status={self.param} 
                            WHERE id={self.param}
                        """, ('failed',schedule_id,))
                    elif successful_deliveries == len(recipients):
                        next_run = CampaignScheduleMonitor.calculate_next_run(frequency)
                        if next_run:
                            #next_run = next_run.isoformat()
                            cursor.execute(f"""
                                UPDATE manage_campaign_scheduledmessage 
                                SET status={self.param},scheduled_time={self.param} 
                                WHERE id={self.param}
                            """, ('scheduled',next_run,schedule_id))
                        else:
                            cursor.execute(f"""
                                UPDATE manage_campaign_scheduledmessage 
                                SET status={self.param} 
                                WHERE id={self.param}
                            """, ('completed',schedule_id,))
                    else:
                        next_run = CampaignScheduleMonitor.calculate_next_run(frequency)
                        if next_run:
                            #next_run = next_run.isoformat()
                            cursor.execute(f"""
                                UPDATE manage_campaign_scheduledmessage 
                                SET status={self.param},scheduled_time={self.param} 
                                WHERE id={self.param}
                            """, ('scheduled_warning',next_run,schedule_id))
                        else:
                            cursor.execute(f"""
                                UPDATE manage_campaign_scheduledmessage 
                                SET status={self.param} 
                                WHERE id={self.param}
                            """, ('warning',schedule_id,))
        except Exception as e:
            self.logger.error(e)
            traceback.print_exc()
        finally:
            self.logger.info("Stopping campaign schedule task...")


if __name__ == "__main__":
    campaign_instance = CampaignScheduleMonitor()
    while True:
        campaign_instance.process_campaign_schedule_message()
        # TODO: Increase this to ~1 minute in production
        time.sleep(600)