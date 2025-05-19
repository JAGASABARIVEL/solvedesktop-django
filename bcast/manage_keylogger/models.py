from django.db import models
from django.conf import settings

class KeyLogger(models.Model):
    organization = models.ForeignKey(
        settings.ORG_MODEL, on_delete=models.CASCADE, related_name='keylogs'
    )
    emp = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, related_name='keylogs'
    )
    date = models.TextField()
    app_details = models.TextField()
    idle_time = models.IntegerField()

    def __str__(self):
        return f"KeyLogger Entry for {self.emp_id} on {self.date}"
