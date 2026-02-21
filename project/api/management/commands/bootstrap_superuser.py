import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update a superuser from env vars for non-interactive deployments."

    def handle(self, *args, **options):
        username = (os.getenv("DJANGO_BOOTSTRAP_SUPERUSER_USERNAME") or "").strip()
        password = os.getenv("DJANGO_BOOTSTRAP_SUPERUSER_PASSWORD") or ""
        email = (os.getenv("DJANGO_BOOTSTRAP_SUPERUSER_EMAIL") or "").strip()

        if not username or not password:
            self.stdout.write(
                self.style.WARNING(
                    "Skipping superuser bootstrap: set DJANGO_BOOTSTRAP_SUPERUSER_USERNAME and "
                    "DJANGO_BOOTSTRAP_SUPERUSER_PASSWORD to enable it."
                )
            )
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email or f"{username}@example.com"},
        )

        if email:
            user.email = email
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} superuser: {username}"))
