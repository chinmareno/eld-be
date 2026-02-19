from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    driver_name = models.CharField(max_length=100, default="Anonymous Driver")
    home_terminal_tz = models.CharField(max_length=50, default="America/New_York")
    current_cycle_used = models.DecimalField(max_digits=4, decimal_places=2, default=0.00)
