import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import NotFound
from rest_framework_simplejwt.tokens import RefreshToken

from .models import StatusEvent, Trip
from .serializer import (
    LoginSerializer,
    StatusEventCreateSerializer,
    StatusEventSerializer,
    TripCompleteSerializer,
    TripCreateSerializer,
    TripSummarySerializer,
    UserSerializer,
)
from datetime import timedelta
from decimal import Decimal


def _token_max_age(setting_name):
    lifetime = settings.SIMPLE_JWT[setting_name]
    return int(lifetime.total_seconds())


def _set_auth_cookies(response, access_token, refresh_token):
    response.set_cookie(
        key=settings.JWT_AUTH_COOKIE,
        value=str(access_token),
        max_age=_token_max_age("ACCESS_TOKEN_LIFETIME"),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path="/",
    )
    response.set_cookie(
        key=settings.JWT_AUTH_REFRESH_COOKIE,
        value=str(refresh_token),
        max_age=_token_max_age("REFRESH_TOKEN_LIFETIME"),
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path="/",
    )


def _clear_auth_cookies(response):
    response.delete_cookie(
        key=settings.JWT_AUTH_COOKIE,
        path="/",
        samesite=settings.JWT_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        key=settings.JWT_AUTH_REFRESH_COOKIE,
        path="/",
        samesite=settings.JWT_COOKIE_SAMESITE,
    )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        response = Response(
            {
                "detail": "Login successful.",
                "user": UserSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )
        _set_auth_cookies(response, access, refresh)
        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        response = Response(
            {"detail": "Logout successful."},
            status=status.HTTP_200_OK,
        )
        _clear_auth_cookies(response)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"user": UserSerializer(request.user).data}, status=status.HTTP_200_OK)


class GeocodeSearchView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        throttled_response = _check_geocode_rate_limit(request)
        if throttled_response is not None:
            return throttled_response

        query = (request.query_params.get("q") or "").strip()
        if len(query) < 3:
            return Response({"results": []}, status=status.HTTP_200_OK)

        params = {
            "format": "json",
            "q": query,
            "limit": "5",
        }
        try:
            data = _fetch_nominatim_json("search", params)
        except Exception:
            return Response(
                {"detail": "Unable to search locations."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        results = []
        for item in data:
            try:
                lat = float(item["lat"])
                lng = float(item["lon"])
            except (TypeError, ValueError, KeyError):
                continue
            results.append(
                {
                    "addressName": item.get("display_name") or "Selected location",
                    "lat": lat,
                    "lng": lng,
                }
            )
        return Response({"results": results}, status=status.HTTP_200_OK)


class GeocodeReverseView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        throttled_response = _check_geocode_rate_limit(request)
        if throttled_response is not None:
            return throttled_response

        try:
            lat = float(request.query_params.get("lat"))
            lng = float(request.query_params.get("lng"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid coordinates."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        params = {
            "format": "json",
            "lat": f"{lat}",
            "lon": f"{lng}",
        }
        try:
            data = _fetch_nominatim_json("reverse", params)
        except Exception:
            return Response(
                {"detail": "Unable to resolve address."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        result = {
            "addressName": data.get("display_name") or "Unknown",
            "lat": lat,
            "lng": lng,
        }
        return Response({"result": result}, status=status.HTTP_200_OK)


class TripCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TripCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        route_summary = _build_route_summary(
            (float(data["current_location_lat"]), float(data["current_location_lng"])),
            (float(data["pickup_location_lat"]), float(data["pickup_location_lng"])),
            (float(data["dropoff_location_lat"]), float(data["dropoff_location_lng"])),
        )

        trip = Trip.objects.create(
            user=request.user,
            current_location_name=data["current_location_name"],
            current_location_lat=data["current_location_lat"],
            current_location_lng=data["current_location_lng"],
            pickup_location_name=data["pickup_location_name"],
            pickup_location_lat=data["pickup_location_lat"],
            pickup_location_lng=data["pickup_location_lng"],
            dropoff_location_name=data["dropoff_location_name"],
            dropoff_location_lat=data["dropoff_location_lat"],
            dropoff_location_lng=data["dropoff_location_lng"],
            cycle_used_hours=data["cycle_used_hours"],
            current_status=data["start_status"],
            current_status_started_at=data["start_time"],
            route_distance_miles=route_summary.get("distance_miles"),
            route_duration_hours=route_summary.get("duration_hours"),
            route_polyline=route_summary.get("polyline"),
            route_stops=route_summary.get("stops"),
        )

        return Response(
            {"trip_id": str(trip.id), "trip": TripSummarySerializer(trip).data},
            status=status.HTTP_201_CREATED,
        )


class TripSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, trip_id):
        trip = _get_trip_or_404(request.user, trip_id)
        return Response({"trip": TripSummarySerializer(trip).data}, status=status.HTTP_200_OK)


class TripRouteView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, trip_id):
        trip = _get_trip_or_404(request.user, trip_id)
        return Response(
            {
                "distance_miles": trip.route_distance_miles,
                "eta_hours": trip.route_duration_hours,
                "stops": trip.route_stops or [],
                "polyline": trip.route_polyline,
            },
            status=status.HTTP_200_OK,
        )


class StatusEventCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, trip_id):
        trip = _get_trip_or_404(request.user, trip_id)
        if trip.completed_at:
            return Response(
                {"detail": "Trip is already completed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = StatusEventCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if trip.current_status is None or trip.current_status_started_at is None:
            return Response(
                {"detail": "Trip has no active status to close."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if data["effective_at"] <= trip.current_status_started_at:
            return Response(
                {"detail": "Status change must be after the current status start time."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            event = StatusEvent.objects.create(
                trip=trip,
                status=trip.current_status,
                start_time=trip.current_status_started_at,
                end_time=data["effective_at"],
            )
            trip.current_status = data["status"]
            trip.current_status_started_at = data["effective_at"]
            trip.save(update_fields=["current_status", "current_status_started_at"])

        warnings = _calculate_warnings(trip)
        return Response(
            {
                "event": StatusEventSerializer(event).data,
                "trip": TripSummarySerializer(trip).data,
                "warnings": warnings,
            },
            status=status.HTTP_201_CREATED,
        )


class TripCompleteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, trip_id):
        trip = _get_trip_or_404(request.user, trip_id)
        if trip.completed_at:
            return Response(
                {"detail": "Trip is already completed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TripCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        effective_at = serializer.validated_data["effective_at"]

        if trip.current_status is None or trip.current_status_started_at is None:
            return Response(
                {"detail": "Trip has no active status to close."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if effective_at <= trip.current_status_started_at:
            return Response(
                {"detail": "Completion time must be after the current status start time."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            event = StatusEvent.objects.create(
                trip=trip,
                status=trip.current_status,
                start_time=trip.current_status_started_at,
                end_time=effective_at,
            )
            trip.current_status = None
            trip.current_status_started_at = None
            trip.completed_at = effective_at
            trip.save(update_fields=["current_status", "current_status_started_at", "completed_at"])

        warnings = _calculate_warnings(trip)
        return Response(
            {
                "event": StatusEventSerializer(event).data,
                "trip": TripSummarySerializer(trip).data,
                "warnings": warnings,
            },
            status=status.HTTP_200_OK,
        )


class EldLogsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, trip_id):
        trip = _get_trip_or_404(request.user, trip_id)
        events = list(trip.status_events.order_by("start_time"))
        logs = _build_eld_logs(events)
        return Response({"trip_id": str(trip.id), "logs": logs}, status=status.HTTP_200_OK)


def _get_trip_or_404(user, trip_id):
    try:
        return Trip.objects.get(id=trip_id, user=user)
    except Trip.DoesNotExist:
        raise NotFound(detail="Trip not found.")


def _get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _check_geocode_rate_limit(request):
    client_ip = _get_client_ip(request)
    cache_key = f"geocode-rate:{client_ip}"
    was_added = cache.add(cache_key, "1", timeout=1)
    if was_added:
        return None
    return Response(
        {"detail": "Too many geocoding requests. Please slow down."},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )


def _fetch_nominatim_json(endpoint, params):
    encoded_params = urlencode(params)
    cache_key = f"nominatim:{endpoint}:{encoded_params}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    request = Request(
        f"https://nominatim.openstreetmap.org/{endpoint}?{encoded_params}",
        headers={
            "User-Agent": settings.GEOCODING_USER_AGENT,
            "Accept-Language": "en",
        },
    )
    with urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    cache.set(cache_key, data, timeout=300)
    return data


def _build_route_summary(current_location, pickup_location, dropoff_location):
    coords = [current_location, pickup_location, dropoff_location]

    try:
        route = _fetch_route(coords)
    except Exception:
        return {}

    if not route:
        return {}

    distance_miles = Decimal(route["distance_meters"]) / Decimal("1609.344")
    duration_hours = Decimal(route["duration_seconds"]) / Decimal("3600")
    stops = _estimate_stops(float(duration_hours))

    return {
        "distance_miles": round(distance_miles, 2),
        "duration_hours": round(duration_hours, 2),
        "polyline": route.get("polyline"),
        "stops": stops,
    }


def _fetch_route(coords):
    coords_str = ";".join([f"{lon},{lat}" for lat, lon in coords])
    params = urlencode({"overview": "full", "geometries": "polyline"})
    request = Request(
        f"https://router.project-osrm.org/route/v1/driving/{coords_str}?{params}",
        headers={"User-Agent": "spotter-eld/1.0"},
    )
    with urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    routes = data.get("routes")
    if not routes:
        return None
    route = routes[0]
    return {
        "distance_meters": route.get("distance"),
        "duration_seconds": route.get("duration"),
        "polyline": route.get("geometry"),
    }


def _estimate_stops(duration_hours):
    stops = []
    driving_hours = 0.0
    while driving_hours + 8 <= duration_hours:
        driving_hours += 8
        stops.append(
            {
                "type": "break",
                "eta_hours": round(driving_hours, 2),
                "duration_hours": 0.5,
                "label": "30-min break",
            }
        )
        if driving_hours + 3 <= duration_hours:
            driving_hours += 3
            if driving_hours >= 11:
                stops.append(
                    {
                        "type": "rest",
                        "eta_hours": round(driving_hours, 2),
                        "duration_hours": 10,
                        "label": "10-hour rest",
                    }
                )
                driving_hours += 10
    return stops


def _build_eld_logs(events):
    logs_by_date = {}
    for event in events:
        current = timezone.localtime(event.start_time)
        end = timezone.localtime(event.end_time)
        while current.date() <= end.date():
            day_end = current.replace(hour=23, minute=59, second=59, microsecond=999999)
            segment_end = min(end, day_end)
            key = current.date().isoformat()
            logs_by_date.setdefault(key, []).append(
                {
                    "status": event.status,
                    "start_time": current.isoformat(),
                    "end_time": segment_end.isoformat(),
                }
            )
            current = segment_end + timedelta(microseconds=1)
    return [
        {"date": date, "entries": entries}
        for date, entries in sorted(logs_by_date.items(), key=lambda item: item[0])
    ]


def _calculate_warnings(trip):
    events = list(trip.status_events.order_by("start_time"))
    warnings = []

    shift_start = None
    last_break_end = None
    driving_since_break = timedelta()
    driving_total = timedelta()
    on_duty_total = timedelta()

    for event in events:
        duration = event.end_time - event.start_time
        if event.status in {Trip.STATUS_OFF_DUTY, Trip.STATUS_SLEEPER} and duration >= timedelta(hours=10):
            shift_start = event.end_time
            driving_since_break = timedelta()
            driving_total = timedelta()
            on_duty_total = timedelta()
            last_break_end = event.end_time
            continue

        if event.status in {Trip.STATUS_OFF_DUTY, Trip.STATUS_SLEEPER} and duration >= timedelta(minutes=30):
            last_break_end = event.end_time
            driving_since_break = timedelta()

        if shift_start is None:
            shift_start = event.start_time

        if event.status == Trip.STATUS_DRIVING:
            driving_total += duration
            driving_since_break += duration

        if event.status in {Trip.STATUS_DRIVING, Trip.STATUS_ON_DUTY}:
            on_duty_total += duration

    if driving_total > timedelta(hours=11):
        warnings.append("Driving time exceeds 11-hour limit since last 10-hour rest.")
    if on_duty_total > timedelta(hours=14):
        warnings.append("On-duty window exceeds 14-hour limit since last 10-hour rest.")
    if driving_since_break > timedelta(hours=8):
        warnings.append("30-minute break required after 8 cumulative driving hours.")

    cycle_used = Decimal(trip.cycle_used_hours or 0)
    on_duty_hours = Decimal(on_duty_total.total_seconds() / 3600)
    if cycle_used + on_duty_hours > Decimal("70"):
        warnings.append("Planned work exceeds 70-hour / 8-day cycle limit.")

    return warnings
