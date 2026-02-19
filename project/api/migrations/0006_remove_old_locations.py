from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ("api", "0005_trip_locations"),
    ]

    operations = [
        migrations.RemoveField(model_name="trip", name="current_location"),
        migrations.RemoveField(model_name="trip", name="pickup_location"),
        migrations.RemoveField(model_name="trip", name="dropoff_location"),
    ]
