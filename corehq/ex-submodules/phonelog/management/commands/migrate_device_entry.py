from __future__ import print_function
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from phonelog.models import OldDeviceReportEntry, DeviceReportEntry


class Command(BaseCommand):
    help = "Migrate device reports to partitioned table"

    def handle(self, *args, **options):
        partitioned_table = DeviceReportEntry._meta.db_table
        old_table = OldDeviceReportEntry._meta.db_table

        now = datetime.utcnow()
        oldest_date = now - timedelta(days=settings.DAYS_TO_KEEP_DEVICE_LOGS)
        current = now
        while current > oldest_date:
            hour_ago = current - timedelta(hours=1)
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO " + partitioned_table + " " +
                    "SELECT * FROM " + old_table + " " +
                    "WHERE server_date BETWEEN %s AND %s",
                    [hour_ago, current]
                )
            print("Inserted device logs from %s to %s" % (hour_ago, current))
            current = hour_ago