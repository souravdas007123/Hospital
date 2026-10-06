from django.core.management.base import BaseCommand

from accounts.permissions import create_role_groups


class Command(BaseCommand):

    help = "Create and configure HMS role groups and permissions"

    def handle(self, *args, **options):

        self.stdout.write(
            self.style.WARNING(
                "Setting up HMS roles and permissions..."
            )
        )

        create_role_groups()

        self.stdout.write(
            self.style.SUCCESS(
                "HMS roles and permissions setup completed."
            )
        )