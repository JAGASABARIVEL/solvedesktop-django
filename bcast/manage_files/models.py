import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta


class File(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.TextField()
    size_gb = models.FloatField()
    s3_key = models.TextField()  # Stores S3 path
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE)  # Folder hierarchy
    created_at = models.DateTimeField(auto_now_add=True)
    is_deleted = models.BooleanField(default=False)

    def is_folder(self):
        return self.s3_key.endswith("/")  # Folders are just keys ending with "/"

    def __str__(self):
        return self.s3_key


class FilePermission(models.Model):
    file = models.ForeignKey(File, on_delete=models.CASCADE, related_name="permissions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    can_read = models.BooleanField(default=True)
    can_write = models.BooleanField(default=False)
    inherited = models.BooleanField(default=False)  # Indicates if permission was inherited

    class Meta:
        unique_together = ("file", "user")  # Prevent duplicate entries

    def __str__(self):
        return f"{self.user} - {self.file.name} (Read: {self.can_read}, Write: {self.can_write})"

    def apply_to_children(self):
        """Inherit permissions for subfolders & files when a folder is shared."""
        if self.file.is_folder:
            children = File.objects.filter(parent=self.file)
            for child in children:
                FilePermission.objects.get_or_create(
                    file=child,
                    user=self.user,
                    defaults={"can_read": self.can_read, "can_write": self.can_write, "inherited": True}
                )


class FileStorageEvent(models.Model):
    file_id = models.ForeignKey(File, on_delete=models.SET_NULL, null=True, blank=True)
    file_name = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    size_gb = models.FloatField()
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)

    def get_cost_for_month(self):
        #usage_ratio = delta_days / month_days
        cost = self.size_gb * settings.STORAGE_COST_PER_GB_PER_MONTH
        return cost

    def get_total_cost_until(self, target_date) -> float:
        """Returns the cumulative storage cost from file creation month up to target_date (inclusive)."""
        total_cost = 0.0
        if self.start_time > target_date:
            return 0.0  # File not yet created in selected month
        # Start from the month of file creation
        current = self.start_time.replace(day=1)
        # Iterate month-by-month until target_date
        while current <= target_date.replace(day=1):
            total_cost += self.get_cost_for_month()
            current += relativedelta(months=1)
        return total_cost


class FileDownloadEvent(models.Model):
    file_id = models.ForeignKey(File, on_delete=models.SET_NULL, null=True, blank=True)
    file_name = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    size_gb = models.FloatField()
    timestamp = models.DateTimeField(default=timezone.now)

    def get_cost(self):
        return self.size_gb * settings.DOWNLOAD_COST_PER_GB


class PaymentFiles(models.Model):
    # The payment can only be made from wallet
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    month = models.IntegerField()
    year = models.IntegerField()
    amount_paid = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "month", "year")

    def __str__(self):
        return f"{self.user.username} - {self.month}/{self.year} - ₹{self.amount_paid}"
