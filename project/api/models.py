from django.db import models
from django.contrib.auth.models import User
import uuid

class Driver(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE)  # links to auth user
    driver_name = models.CharField(max_length=100, default="Anonymous Driver")
    home_terminal_tz = models.CharField(max_length=50, default='America/New_York')
    current_cycle_used = models.DecimalField(max_digits=4, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'drivers'

    def __str__(self):
        return self.driver_name
