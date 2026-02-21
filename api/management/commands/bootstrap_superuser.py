from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create/update fixed assessment superuser for non-interactive deploys."

    def handle(self, *args, **options):
        username = "superadmin"
        email = "superadmin@gmail.com"
        password = "superadmin"

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "current_cycle_used": Decimal("0.00"),
            },
        )

        user.email = email
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        if hasattr(user, "current_cycle_used"):
            user.current_cycle_used = Decimal("0.00")
        user.set_password(password)
        user.save()

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} superuser: {username}"))
