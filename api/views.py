import json
import hashlib
import logging
import math
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

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
from datetime import date, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

ELD_DEFAULT_LIMIT = 20
ELD_MAX_LIMIT = 100
ELD_MAX_RANGE_DAYS = 30
PICKUP_DROPOFF_BUFFER_HOURS = Decimal("1.0")
FUEL_STOP_INTERVAL_MILES = 1000
FUEL_STOP_DURATION_HOURS = 0.5


class LoginView(APIView):
    authentication_classes = []
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
                "access": str(access),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )
        return response


class LogoutView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        return Response(
            {"detail": "Logout successful."},
            status=status.HTTP_200_OK,
        )


class RefreshView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            refresh = RefreshToken(refresh_token)
            access = refresh.access_token
        except Exception:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(
            {"access": str(access)},
            status=status.HTTP_200_OK,
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"user": UserSerializer(request.user).data}, status=status.HTTP_200_OK)


class GeocodeSearchView(APIView):
    authentication_classes = []
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
    authentication_classes = []
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


class NearbyPoiView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            lat = float(request.query_params.get("lat"))
            lng = float(request.query_params.get("lng"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid coordinates."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        radius_km = _parse_int_in_range(
            request.query_params.get("radius_km"),
            default=settings.POI_DEFAULT_RADIUS_KM,
            minimum=1,
            maximum=50,
        )
        limit_per_category = _parse_int_in_range(
            request.query_params.get("limit"),
            default=settings.POI_DEFAULT_LIMIT_PER_CATEGORY,
            minimum=1,
            maximum=10,
        )

        try:
            results = _fetch_nearby_pois(
                lat=lat,
                lng=lng,
                radius_km=radius_km,
                limit_per_category=limit_per_category,
            )
        except Exception as exc:
            logger.warning("Unable to fetch nearby POIs: %s", exc)
            return Response(
                {"detail": "Unable to load nearby fuel and parking points."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"results": results}, status=status.HTTP_200_OK)


class ActiveTripView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        trip = _get_active_trip(request.user)
        if trip is None:
            return Response({"trip": None}, status=status.HTTP_200_OK)
        return Response({"trip": TripSummarySerializer(trip).data}, status=status.HTTP_200_OK)


class TripCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        active_trip = _get_active_trip(request.user)
        if active_trip is not None:
            return Response(
                {"detail": "You already have an active trip. Complete it before creating a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TripCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        latest_completed_at = _get_latest_completed_at(request.user)
        if latest_completed_at is not None and data["start_time"] < latest_completed_at:
            return Response(
                {
                    "detail": (
                        "Start time must be on or after your most recent completed trip time."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

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


class TripRoutePreviewView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TripCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        route_summary = _build_route_summary(
            (float(data["current_location_lat"]), float(data["current_location_lng"])),
            (float(data["pickup_location_lat"]), float(data["pickup_location_lng"])),
            (float(data["dropoff_location_lat"]), float(data["dropoff_location_lng"])),
        )

        return Response(
            {
                "distance_miles": route_summary.get("distance_miles"),
                "eta_hours": route_summary.get("duration_hours"),
                "stops": route_summary.get("stops", []),
                "polyline": route_summary.get("polyline"),
            },
            status=status.HTTP_200_OK,
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
        if (
            trip.route_polyline is None
            or trip.route_distance_miles is None
            or trip.route_duration_hours is None
        ):
            refreshed_route = _build_route_summary(
                (float(trip.current_location_lat), float(trip.current_location_lng)),
                (float(trip.pickup_location_lat), float(trip.pickup_location_lng)),
                (float(trip.dropoff_location_lat), float(trip.dropoff_location_lng)),
            )
            if refreshed_route:
                trip.route_distance_miles = refreshed_route.get("distance_miles")
                trip.route_duration_hours = refreshed_route.get("duration_hours")
                trip.route_polyline = refreshed_route.get("polyline")
                trip.route_stops = refreshed_route.get("stops")
                trip.save(
                    update_fields=[
                        "route_distance_miles",
                        "route_duration_hours",
                        "route_polyline",
                        "route_stops",
                    ]
                )

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


class TestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"message": "Hello from the Django backend! The API is alive."}, status=status.HTTP_200_OK)


class EldLogsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, trip_id):
        trip = _get_trip_or_404(request.user, trip_id)
        segments = _collect_eld_segments(trip)
        logs = _build_eld_logs(segments, tzinfo=_get_user_timezone(request.user))
        return Response({"trip_id": str(trip.id), "logs": logs}, status=status.HTTP_200_OK)


class CompletedEldLogsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            start_date = _parse_iso_date(
                request.query_params.get("start_date"),
                field_name="start_date",
            )
            end_date = _parse_iso_date(
                request.query_params.get("end_date"),
                field_name="end_date",
            )
            cursor = _parse_iso_date(
                request.query_params.get("cursor"),
                field_name="cursor",
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if start_date and end_date and end_date < start_date:
            return Response(
                {"detail": "end_date must be on or after start_date."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if start_date and end_date and (end_date - start_date).days > ELD_MAX_RANGE_DAYS:
            return Response(
                {"detail": f"Date range cannot exceed {ELD_MAX_RANGE_DAYS} days."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        limit = _parse_int_in_range(
            request.query_params.get("limit"),
            default=ELD_DEFAULT_LIMIT,
            minimum=1,
            maximum=ELD_MAX_LIMIT,
        )

        logs = _get_completed_eld_logs_desc(
            request.user,
            tzinfo=_get_user_timezone(request.user),
        )
        filtered_logs = _filter_completed_logs_by_query(
            logs,
            start_date=start_date,
            end_date=end_date,
            cursor=cursor,
        )

        page_logs = filtered_logs[:limit]
        has_more = len(filtered_logs) > limit
        next_cursor = page_logs[-1]["date"] if has_more and page_logs else None

        return Response(
            {
                "logs": page_logs,
                "has_more": has_more,
                "next_cursor": next_cursor,
            },
            status=status.HTTP_200_OK,
        )


def _get_trip_or_404(user, trip_id):
    try:
        return Trip.objects.get(id=trip_id, user=user)
    except Trip.DoesNotExist:
        raise NotFound(detail="Trip not found.")


def _get_active_trip(user):
    return (
        Trip.objects.filter(
            user=user,
            completed_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )


def _get_latest_completed_at(user):
    return (
        Trip.objects.filter(
            user=user,
            completed_at__isnull=False,
        )
        .order_by("-completed_at")
        .values_list("completed_at", flat=True)
        .first()
    )


def _parse_iso_date(raw_value, *, field_name):
    if raw_value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw_value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format.") from exc


def _get_completed_eld_logs_desc(user, *, tzinfo):
    segments = []
    events = StatusEvent.objects.filter(
        trip__user=user,
        trip__completed_at__isnull=False,
    ).order_by("start_time")

    for event in events:
        if event.end_time <= event.start_time:
            continue
        segments.append(
            {
                "status": event.status,
                "start_time": event.start_time,
                "end_time": event.end_time,
            }
        )

    logs = _build_eld_logs(segments, tzinfo=tzinfo)
    logs.reverse()
    return logs


def _filter_completed_logs_by_query(logs, *, start_date, end_date, cursor):
    start_text = start_date.isoformat() if start_date else None
    end_text = end_date.isoformat() if end_date else None
    cursor_text = cursor.isoformat() if cursor else None

    filtered = []
    for log in logs:
        log_date = log["date"]
        if start_text and log_date < start_text:
            continue
        if end_text and log_date > end_text:
            continue
        if cursor_text and log_date >= cursor_text:
            continue
        filtered.append(log)
    return filtered


def _get_user_timezone(user):
    tz_name = getattr(user, "home_terminal_tz", None)
    if not tz_name:
        return timezone.get_current_timezone()
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.get_current_timezone()


def _get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _check_geocode_rate_limit(request):
    client_ip = _get_client_ip(request)
    second_bucket = int(time.time())
    cache_key = f"geocode-rate:{client_ip}:{second_bucket}"
    current_count = cache.get(cache_key)
    if current_count is None:
        cache.set(cache_key, 1, timeout=2)
        return None
    if current_count < 3:
        cache.set(cache_key, current_count + 1, timeout=2)
        return None
    return Response(
        {"detail": "Too many geocoding requests. Please slow down."},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )


def _parse_int_in_range(raw_value, default, minimum, maximum):
    if raw_value is None:
        return default
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _build_overpass_query(lat, lng, radius_meters):
    lat_text = f"{lat:.6f}"
    lng_text = f"{lng:.6f}"
    return f"""
[out:json][timeout:20];
(
  nwr["amenity"="fuel"](around:{radius_meters},{lat_text},{lng_text});
  nwr["amenity"="parking"](around:{radius_meters},{lat_text},{lng_text});
  nwr["highway"="rest_area"](around:{radius_meters},{lat_text},{lng_text});
  nwr["highway"="services"](around:{radius_meters},{lat_text},{lng_text});
);
out center;
""".strip()


def _fetch_overpass_json(query):
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    cache_key = f"overpass:{query_hash}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    payload = urlencode({"data": query}).encode("utf-8")
    request = Request(
        settings.POI_BASE_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": settings.POI_USER_AGENT,
        },
    )

    with urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))

    cache.set(cache_key, data, timeout=300)
    return data


def _extract_poi_coordinate(element):
    lat = element.get("lat")
    lng = element.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return float(lat), float(lng)

    center = element.get("center")
    if isinstance(center, dict):
        center_lat = center.get("lat")
        center_lng = center.get("lon")
        if isinstance(center_lat, (int, float)) and isinstance(center_lng, (int, float)):
            return float(center_lat), float(center_lng)

    return None


def _haversine_distance_miles(origin_lat, origin_lng, destination_lat, destination_lng):
    lat1 = math.radians(origin_lat)
    lng1 = math.radians(origin_lng)
    lat2 = math.radians(destination_lat)
    lng2 = math.radians(destination_lng)
    delta_lat = lat2 - lat1
    delta_lng = lng2 - lng1

    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    miles = 3958.7613 * c
    return miles


def _fetch_nearby_pois(lat, lng, radius_km, limit_per_category):
    radius_meters = int(radius_km * 1000)
    query = _build_overpass_query(lat, lng, radius_meters)
    data = _fetch_overpass_json(query)
    elements = data.get("elements")
    if not isinstance(elements, list):
        return []

    by_category = {"fuel": [], "parking": [], "rest_area": []}

    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags")
        if not isinstance(tags, dict):
            continue

        category = None
        if tags.get("amenity") == "fuel":
            category = "fuel"
        elif tags.get("amenity") == "parking":
            category = "parking"
        elif tags.get("highway") in {"rest_area", "services"}:
            category = "rest_area"

        if category is None:
            continue

        coordinate = _extract_poi_coordinate(element)
        if coordinate is None:
            continue

        poi_lat, poi_lng = coordinate
        distance_miles = _haversine_distance_miles(lat, lng, poi_lat, poi_lng)
        name = tags.get("name")
        if not name:
            if category == "fuel":
                name = "Fuel stop"
            elif category == "parking":
                name = "Parking area"
            else:
                name = "Rest area"

        by_category[category].append(
            {
                "id": f"{element.get('type', 'node')}-{element.get('id', 'unknown')}",
                "name": name,
                "category": category,
                "lat": round(poi_lat, 6),
                "lng": round(poi_lng, 6),
                "distance_miles": round(distance_miles, 2),
            }
        )

    ordered = []
    for category in ("fuel", "parking", "rest_area"):
        category_items = by_category[category]
        category_items.sort(key=lambda item: item["distance_miles"])
        ordered.extend(category_items[:limit_per_category])

    return ordered


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
    except Exception as exc:
        logger.warning("Unable to generate route summary: %s", exc)
        return {}

    if not route:
        logger.warning("Route provider returned no route geometry.")
        return {}

    distance_meters = route.get("distance_meters")
    duration_seconds = route.get("duration_seconds")
    if not isinstance(distance_meters, (int, float)) or not isinstance(duration_seconds, (int, float)):
        logger.warning("Route summary missing numeric distance or duration.")
        return {}

    distance_miles = Decimal(str(distance_meters)) / Decimal("1609.344")
    driving_duration_hours = Decimal(str(duration_seconds)) / Decimal("3600")
    planned_duration_hours = driving_duration_hours + PICKUP_DROPOFF_BUFFER_HOURS
    stops = _estimate_stops(
        driving_duration_hours=float(driving_duration_hours),
        distance_miles=float(distance_miles),
    )

    return {
        "distance_miles": round(distance_miles, 2),
        "duration_hours": round(planned_duration_hours, 2),
        "polyline": route.get("polyline"),
        "stops": stops,
    }


def _fetch_route(coords):
    if not settings.ORS_API_KEY:
        raise RuntimeError("ORS_API_KEY is not configured.")

    ors_coordinates = [[lon, lat] for lat, lon in coords]
    payload = {
        "coordinates": ors_coordinates,
        # Allow snapping waypoints that are slightly off-road (map center picks often land on parcels).
        "radiuses": [settings.ORS_SNAP_RADIUS_METERS] * len(ors_coordinates),
    }
    request = Request(
        settings.ORS_DIRECTIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": settings.ORS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json, application/geo+json",
            "User-Agent": settings.ROUTING_USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"ORS request failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"ORS request failed: {exc.reason}") from exc
    features = data.get("features")
    if not features:
        return None
    route = features[0]
    properties = route.get("properties", {})
    summary = properties.get("summary", {})
    geometry = route.get("geometry", {})
    coordinates = geometry.get("coordinates") or []
    if not coordinates:
        return None

    lat_lng_polyline = []
    for point in coordinates:
        if not isinstance(point, list) or len(point) < 2:
            continue
        lng = point[0]
        lat = point[1]
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        lat_lng_polyline.append([lat, lng])

    if not lat_lng_polyline:
        return None

    return {
        "distance_meters": summary.get("distance"),
        "duration_seconds": summary.get("duration"),
        "polyline": json.dumps(lat_lng_polyline),
    }


def _estimate_stops(*, driving_duration_hours, distance_miles):
    stops = []
    if driving_duration_hours <= 0:
        return stops

    # Schedule fuel stops at least every 1,000 miles over the planned route.
    if distance_miles > 0:
        fuel_stop_count = int(distance_miles // FUEL_STOP_INTERVAL_MILES)
        for index in range(1, fuel_stop_count + 1):
            marker_miles = index * FUEL_STOP_INTERVAL_MILES
            if marker_miles >= distance_miles:
                break
            progress_ratio = marker_miles / distance_miles
            eta_hours = max(0.0, min(driving_duration_hours, driving_duration_hours * progress_ratio))
            stops.append(
                {
                    "type": "fuel",
                    "eta_hours": round(eta_hours, 2),
                    "duration_hours": FUEL_STOP_DURATION_HOURS,
                    "label": f"Fuel stop near {marker_miles:,} miles",
                }
            )

    break_hour = 8.0
    while break_hour <= driving_duration_hours:
        stops.append(
            {
                "type": "break",
                "eta_hours": round(break_hour, 2),
                "duration_hours": 0.5,
                "label": "30-min break",
            }
        )
        break_hour += 8

    # Show the first 10-hour reset once, then only show the next reset at 70-hour cycle threshold.
    if driving_duration_hours >= 11:
        stops.append(
            {
                "type": "rest",
                "eta_hours": 11.0,
                "duration_hours": 10,
                "label": "10-hour off-duty reset",
            }
        )

    if driving_duration_hours >= 70:
        stops.append(
            {
                "type": "rest",
                "eta_hours": 70.0,
                "duration_hours": 10,
                "label": "10-hour cycle reset (70-hour limit)",
            }
        )

    stops.sort(key=lambda item: (item["eta_hours"], item["type"]))
    return stops


def _collect_eld_segments(trip):
    segments = []
    for event in trip.status_events.order_by("start_time"):
        if event.end_time <= event.start_time:
            continue
        segments.append(
            {
                "status": event.status,
                "start_time": event.start_time,
                "end_time": event.end_time,
            }
        )

    if trip.current_status is not None and trip.current_status_started_at is not None:
        segment_end = trip.completed_at or timezone.now()
        if segment_end > trip.current_status_started_at:
            segments.append(
                {
                    "status": trip.current_status,
                    "start_time": trip.current_status_started_at,
                    "end_time": segment_end,
                }
            )

    segments.sort(key=lambda item: item["start_time"])
    return segments


def _build_eld_logs(segments, *, tzinfo):
    logs_by_date = {}
    for segment in segments:
        current = timezone.localtime(segment["start_time"], timezone=tzinfo)
        end = timezone.localtime(segment["end_time"], timezone=tzinfo)
        if end <= current:
            continue

        status_value = segment["status"]
        while current < end:
            next_day_start = (current + timedelta(days=1)).replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            segment_end = min(end, next_day_start)
            if segment_end <= current:
                break
            key = current.date().isoformat()
            logs_by_date.setdefault(key, []).append(
                {
                    "status": status_value,
                    "start_time": current,
                    "end_time": segment_end,
                }
            )
            current = segment_end

    normalized_logs = []
    for date, entries in sorted(logs_by_date.items(), key=lambda item: item[0]):
        sorted_entries = sorted(entries, key=lambda entry: entry["start_time"])
        if not sorted_entries:
            continue

        day_start = sorted_entries[0]["start_time"].replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)

        normalized_entries = []
        cursor = day_start
        for entry in sorted_entries:
            start_time = max(day_start, entry["start_time"])
            end_time = min(day_end, entry["end_time"])
            if end_time <= start_time:
                continue

            if start_time > cursor:
                normalized_entries.append(
                    {
                        "status": Trip.STATUS_OFF_DUTY,
                        "start_time": cursor,
                        "end_time": start_time,
                    }
                )

            normalized_entries.append(
                {
                    "status": entry["status"],
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )
            cursor = end_time

        if cursor < day_end:
            normalized_entries.append(
                {
                    "status": Trip.STATUS_OFF_DUTY,
                    "start_time": cursor,
                    "end_time": day_end,
                }
            )

        normalized_logs.append(
            {
                "date": date,
                "entries": [
                    {
                        "status": entry["status"],
                        "start_time": entry["start_time"].isoformat(),
                        "end_time": entry["end_time"].isoformat(),
                    }
                    for entry in normalized_entries
                ],
            }
        )

    return normalized_logs


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
