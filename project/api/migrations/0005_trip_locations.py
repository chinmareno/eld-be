from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ("api", "0004_trip_status_nullable"),
    ]

    operations = [
        migrations.AddField(
            model_name="trip",
            name="current_location_name",
            field=models.CharField(default="", max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="current_location_lat",
            field=models.DecimalField(decimal_places=6, max_digits=9, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="current_location_lng",
            field=models.DecimalField(decimal_places=6, max_digits=9, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="pickup_location_name",
            field=models.CharField(default="", max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="pickup_location_lat",
            field=models.DecimalField(decimal_places=6, max_digits=9, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="pickup_location_lng",
            field=models.DecimalField(decimal_places=6, max_digits=9, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="dropoff_location_name",
            field=models.CharField(default="", max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="dropoff_location_lat",
            field=models.DecimalField(decimal_places=6, max_digits=9, default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="trip",
            name="dropoff_location_lng",
            field=models.DecimalField(decimal_places=6, max_digits=9, default=0),
            preserve_default=False,
        ),
    ]
