from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import StatusEvent, Trip

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        exclude = ("password",)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class TripCreateSerializer(serializers.Serializer):
    current_location_name = serializers.CharField(max_length=255)
    current_location_lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    current_location_lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    pickup_location_name = serializers.CharField(max_length=255)
    pickup_location_lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    pickup_location_lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    dropoff_location_name = serializers.CharField(max_length=255)
    dropoff_location_lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    dropoff_location_lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    cycle_used_hours = serializers.DecimalField(
        max_digits=4,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("70.00"),
    )
    start_status = serializers.ChoiceField(choices=Trip.STATUS_CHOICES)
    start_time = serializers.DateTimeField()


class StatusEventCreateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Trip.STATUS_CHOICES)
    effective_at = serializers.DateTimeField()


class TripCompleteSerializer(serializers.Serializer):
    effective_at = serializers.DateTimeField()


class StatusEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatusEvent
        fields = ("id", "status", "start_time", "end_time")


class TripSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = (
            "id",
            "current_location_name",
            "current_location_lat",
            "current_location_lng",
            "pickup_location_name",
            "pickup_location_lat",
            "pickup_location_lng",
            "dropoff_location_name",
            "dropoff_location_lat",
            "dropoff_location_lng",
            "cycle_used_hours",
            "current_status",
            "current_status_started_at",
            "route_distance_miles",
            "route_duration_hours",
            "route_polyline",
            "route_stops",
            "created_at",
            "completed_at",
        )
