from django.urls import path
from .views import (
    EldLogsView,
    LoginView,
    LogoutView,
    MeView,
    StatusEventCreateView,
    TripCompleteView,
    TripCreateView,
    TripRouteView,
    TripSummaryView,
)

urlpatterns=[
   path("auth/login/", LoginView.as_view(), name="login"),
   path("auth/logout/", LogoutView.as_view(), name="logout"),
   path("auth/me/", MeView.as_view(), name="me"),
   path("trips/", TripCreateView.as_view(), name="trip-create"),
   path("trips/<uuid:trip_id>/", TripSummaryView.as_view(), name="trip-summary"),
   path("trips/<uuid:trip_id>/route/", TripRouteView.as_view(), name="trip-route"),
   path("trips/<uuid:trip_id>/status-events/", StatusEventCreateView.as_view(), name="trip-status-event"),
   path("trips/<uuid:trip_id>/complete/", TripCompleteView.as_view(), name="trip-complete"),
   path("trips/<uuid:trip_id>/eld-logs/", EldLogsView.as_view(), name="trip-eld-logs"),
]
