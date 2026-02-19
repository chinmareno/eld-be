import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    driver_name = models.CharField(max_length=100, default="Anonymous Driver")
    home_terminal_tz = models.CharField(max_length=50, default="America/New_York")
    current_cycle_used = models.DecimalField(max_digits=4, decimal_places=2, default=0.00)


class Trip(models.Model):
    STATUS_OFF_DUTY = "off_duty"
    STATUS_SLEEPER = "sleeper"
    STATUS_DRIVING = "driving"
    STATUS_ON_DUTY = "on_duty"

    STATUS_CHOICES = [
        (STATUS_OFF_DUTY, "Off Duty"),
        (STATUS_SLEEPER, "Sleeper Berth"),
        (STATUS_DRIVING, "Driving"),
        (STATUS_ON_DUTY, "On Duty (Not Driving)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trips",
    )
    current_location_name = models.CharField(max_length=255)
    current_location_lat = models.DecimalField(max_digits=9, decimal_places=6)
    current_location_lng = models.DecimalField(max_digits=9, decimal_places=6)
    pickup_location_name = models.CharField(max_length=255)
    pickup_location_lat = models.DecimalField(max_digits=9, decimal_places=6)
    pickup_location_lng = models.DecimalField(max_digits=9, decimal_places=6)
    dropoff_location_name = models.CharField(max_length=255)
    dropoff_location_lat = models.DecimalField(max_digits=9, decimal_places=6)
    dropoff_location_lng = models.DecimalField(max_digits=9, decimal_places=6)
    cycle_used_hours = models.DecimalField(max_digits=4, decimal_places=2)
    current_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OFF_DUTY,
        null=True,
        blank=True,
    )
    current_status_started_at = models.DateTimeField(null=True, blank=True)
    route_distance_miles = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    route_duration_hours = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    route_polyline = models.TextField(null=True, blank=True)
    route_stops = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class StatusEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="status_events")
    status = models.CharField(max_length=20, choices=Trip.STATUS_CHOICES)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
