import os
import logging
from contextlib import contextmanager
from dateutil.relativedelta import relativedelta
import psycopg2
import sqlite3
import datetime
from calendar import monthrange


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("UsagePaymentDaemon")

os.environ["PRODUCTION"] = "0"


# DB config from env
DB_CONFIG = {
    "dbname": os.getenv("PG_DB"),
    "user": os.getenv("PG_USER"),
    "password": os.getenv("PG_PASSWORD"),
    "host": os.getenv("PG_HOST"),
    "port": os.getenv("PG_PORT", "5432"),
}

class AppUsageDebitMonitor:
    def __init__(self):
        self.use_sqlite = os.getenv("PRODUCTION") == '1'
        self.db_driver = sqlite3 if self.use_sqlite else psycopg2
        self.db_file = os.getenv("SQLITE_DB", "dev.sqlite3")

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger("AppUsageDebitMonitor")

    @contextmanager
    def get_conn(self):
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
            conn.commit()
        finally:
            conn.close()

    @property
    def param(self):
        return '?' if self.use_sqlite else '%s'

    def call_payment_gateway(self, user_id, amount_due):
        # Dummy Razorpay logic
        logger.info(f"Calling Razorpay for user {user_id}, amount: ₹{amount_due}")
        # Replace with actual Razorpay API integration
        return ("completed", f"txn_{int(datetime.datetime.now().timestamp())}")
    
    
    def get_all_users_with_usage(self, conn, month, year):
        """Return all users who have any usage in the month"""
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT user_id FROM manage_files_filedownloadevent 
                WHERE EXTRACT(MONTH FROM timestamp) = %s AND EXTRACT(YEAR FROM timestamp) = %s
                UNION
                SELECT DISTINCT user_id FROM manage_files_filestorageevent 
                WHERE start_time < %s
            """, (month, year, datetime.date(year, month, monthrange(year, month)[1])))
            return [row[0] for row in cur.fetchall()]
    
    
    def get_user_due_amount(self, conn, user_id, month, year):
        current_month_start = datetime.datetime(year, month, 1)
        next_month_start = current_month_start + relativedelta(months=1)
    
        with conn.cursor() as cur:
            # Storage Cost
            cur.execute("""
                SELECT SUM(cost_month) FROM manage_files_filestorageevent
                WHERE user_id = %s AND start_time < %s
            """, (user_id, next_month_start))
            storage_cost = cur.fetchone()[0] or 0.0
    
            # Download Cost
            cur.execute("""
                SELECT SUM(cost) FROM manage_files_filedownloadevent
                WHERE user_id = %s AND EXTRACT(MONTH FROM timestamp) = %s AND EXTRACT(YEAR FROM timestamp) = %s
            """, (user_id, month, year))
            download_cost = cur.fetchone()[0] or 0.0
    
            total_cost = storage_cost + download_cost
    
            # Payments already made
            cur.execute("""
                SELECT SUM(amount) FROM manage_subscriptions_payment
                WHERE user_id = %s AND transaction_type = 'app_usage' AND timestamp < %s
                AND subscription_id IN (
                    SELECT id FROM manage_subscriptions_usersubscription
                    WHERE plan_id IN (
                        SELECT id FROM manage_subscriptions_subscription
                        WHERE app_id = (
                            SELECT id FROM manage_subscriptions_app WHERE app_name = 'manage_files'
                        )
                    )
                )
            """, (user_id, next_month_start))
            total_paid = cur.fetchone()[0] or 0.0
    
            total_due = round(total_cost - total_paid, 2)
            return total_due if total_due > 0 else 0.0
    
    
    def insert_payment(self, conn, user_id, amount, transaction_id):
        with conn.cursor() as cur:
            # Get active subscription for user and manage_files
            cur.execute("""
                SELECT us.id FROM manage_subscriptions_usersubscription us
                JOIN manage_subscriptions_subscription s ON us.plan_id = s.id
                JOIN manage_subscriptions_app a ON s.app_id = a.id
                WHERE us.user_id = %s AND a.app_name = 'manage_files'
                LIMIT 1
            """, (user_id,))
            result = cur.fetchone()
            if not result:
                logger.warning(f"No subscription found for user {user_id}")
                return
    
            user_sub_id = result[0]
    
            cur.execute("""
                INSERT INTO manage_subscriptions_payment (
                    user_id, subscription_id, transaction_type, amount,
                    status, transaction_id, timestamp
                )
                VALUES (%s, %s, 'app_usage', %s, 'completed', %s, NOW())
            """, (user_id, user_sub_id, amount, transaction_id))
            logger.info(f"Payment recorded for user {user_id}: ₹{amount} - {transaction_id}")
    
    
    def run(self):
        today = datetime.date.today()
        month = today.month
        year = today.year
    
        logger.info(f"Starting payment daemon for {month}/{year}")
        conn = psycopg2.connect(**DB_CONFIG)
    
        try:
            users = self.get_all_users_with_usage(conn, month, year)
    
            for user_id in users:
                due = self.get_user_due_amount(conn, user_id, month, year)
                if due <= 0:
                    continue
    
                status, txn_id = self.call_payment_gateway(user_id, due)
                if status == "completed":
                    self.insert_payment(conn, user_id, due, txn_id)
                else:
                    logger.error(f"Payment failed for user {user_id}")
    
            conn.commit()
    
        except Exception as e:
            logger.exception(f"Daemon error: {str(e)}")
            conn.rollback()
        finally:
            conn.close()



if __name__ == "__main__":
    monitor = AppUsageDebitMonitor()
    monitor.run()
