from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import StatusEvent, Trip, User

admin.site.register(User, UserAdmin)


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "current_status", "created_at", "completed_at")
    list_filter = ("current_status", "created_at", "completed_at")
    search_fields = ("user__username", "current_location_name", "pickup_location_name", "dropoff_location_name")


@admin.register(StatusEvent)
class StatusEventAdmin(admin.ModelAdmin):
    list_display = ("id", "trip", "status", "start_time", "end_time", "created_at")
    list_filter = ("status", "start_time", "created_at")
    search_fields = ("trip__id", "trip__user__username")
