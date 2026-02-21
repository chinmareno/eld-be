from django.conf import settings
from django.http import JsonResponse
from rest_framework.exceptions import AuthenticationFailed

from .authentication import BearerJWTAuthentication


class ApiAuthMiddleware:
    PUBLIC_PATH_PREFIXES = (
        "/api/auth/login/",
        "/api/auth/logout/",
        "/api/auth/refresh/",
        "/api/geocode/search/",
        "/api/geocode/reverse/",
        "/api/trips/preview-route/",
    )

    def __init__(self, get_response):
        self.get_response = get_response
        self.authenticator = BearerJWTAuthentication()

    @staticmethod
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

    def _unauthenticated_response(self, *, clear_cookies=False):
        response = JsonResponse(
            {"detail": "Authentication credentials were not provided."},
            status=401,
        )
        if clear_cookies:
            self._clear_auth_cookies(response)
        return response

    def __call__(self, request):
        path = request.path or ""

        if path.startswith("/api/"):
            if request.method == "OPTIONS":
                return self.get_response(request)

            if any(path.startswith(prefix) for prefix in self.PUBLIC_PATH_PREFIXES):
                return self.get_response(request)

            try:
                auth_result = self.authenticator.authenticate(request)
            except AuthenticationFailed:
                return self._unauthenticated_response(clear_cookies=True)

            if auth_result is None:
                return self._unauthenticated_response()

            user, _token = auth_result
            request.user = user

        return self.get_response(request)
