from django.conf import settings
from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Trip
from .serializer import LoginSerializer, TripCreateSerializer, UserSerializer


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


class TripCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TripCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        trip = Trip.objects.create(
            user=request.user,
            cycle_used_hours=request.user.current_cycle_used,
            current_status="off_duty",
        )

        return Response(
            {
                "trip_id": str(trip.id),
                "current_status": trip.current_status,
                "cycle_used_hours": str(trip.cycle_used_hours),
            },
            status=status.HTTP_201_CREATED,
        )
