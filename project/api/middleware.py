from django.http import JsonResponse
from rest_framework.exceptions import AuthenticationFailed

from .authentication import CookieJWTAuthentication


class ApiAuthMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.authenticator = CookieJWTAuthentication()

    def __call__(self, request):
        path = request.path or ""

        if path.startswith("/api/"):
            if path.startswith("/api/auth/login/") or path.startswith("/api/auth/logout/"):
                return self.get_response(request)

            try:
                auth_result = self.authenticator.authenticate(request)
            except AuthenticationFailed as exc:
                return JsonResponse({"detail": str(exc)}, status=401)

            if auth_result is None:
                return JsonResponse(
                    {"detail": "Authentication credentials were not provided."},
                    status=401,
                )

            user, _token = auth_result
            request.user = user

        return self.get_response(request)
