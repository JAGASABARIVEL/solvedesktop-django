from django.db import models
from django.conf import settings
from django.utils.timezone import now
from datetime import timedelta

class Apps(models.Model):
    app_name = models.TextField(unique=True, help_text="The app this subscription belongs to")

    def __str__(self):
        return self.app_name

class Subscription(models.Model):
    name = models.TextField()
    app = models.ForeignKey(Apps, on_delete=models.CASCADE)
    description = models.TextField(help_text="Short description about the subscription plan")
    price = models.DecimalField(help_text="Price for this subscription", max_digits=10, decimal_places=2, default=0.00)
    duration_days = models.IntegerField(help_text="Duration in days")
    metadata = models.JSONField(default=dict, help_text="Additional data specific to each app")

    def __str__(self):
        return self.name

class UserSubscription(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled')
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plan = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)
    status = models.TextField(choices=STATUS_CHOICES, default='pending')

    def activate_subscription(self):
        """Activate subscription after successful payment"""
        self.start_date = now()
        self.end_date = self.start_date + timedelta(days=self.plan.duration_days)
        self.status = 'active'
        self.save()

    def check_and_update_status(self):
        """Check if subscription has expired and update status accordingly"""
        if self.status == 'active' and self.end_date and self.end_date < now():
            self.status = 'expired'
            self.save(update_fields=['status'])
        return self.status

    def __str__(self):
        return f"{self.user} - {self.plan.name} - {self.status}"

class UserWallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    def credit(self, amount):
        self.balance += amount
        self.save()

    def debit(self, amount):
        if self.balance >= amount:
            self.balance -= amount
            self.save()
            return True
        return False  # Insufficient funds

    def __str__(self):
        return f"{self.user.username} Wallet - ₹{self.balance}"


class Payment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ]

    TRANSACTION_TYPE_CHOICES = [
        ('subscription', 'Subscription'),
        ('wallet_topup', 'Wallet Top-Up'),
        ('app_usage', 'App Usage'),  # <--- For apps like manage_files, whatsapp
    ]
    transaction_id = models.TextField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subscription = models.ForeignKey(UserSubscription, on_delete=models.CASCADE, related_name="payments", null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.TextField(choices=STATUS_CHOICES, default='pending')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES, default='subscription')
    timestamp = models.DateTimeField(auto_now_add=True)

    def complete_payment(self):
        self.status = 'completed'
        self.save()

        if self.transaction_type == "wallet_topup":
            wallet, _ = UserWallet.objects.get_or_create(user=self.user)
            wallet.credit(self.amount)
        elif self.transaction_type == "subscription" and self.subscription:
            self.subscription.activate_subscription()
        elif self.transaction_type == "app_usage":
            # Custom logic to mark usage as paid if needed
            pass

    def __str__(self):
        return f"{self.user.username} - ₹{self.amount} - {self.transaction_type} - {self.status}"

