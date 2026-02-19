import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    driver_name = models.CharField(max_length=100, default="Anonymous Driver")
    home_terminal_tz = models.CharField(max_length=50, default="America/New_York")
    current_cycle_used = models.DecimalField(max_digits=4, decimal_places=2, default=0.00)


class Trip(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trips",
    )
    cycle_used_hours = models.DecimalField(max_digits=4, decimal_places=2, default=0.00)
    current_status = models.CharField(max_length=20, default="off_duty")
    created_at = models.DateTimeField(auto_now_add=True)
