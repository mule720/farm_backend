from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='VideoCall',
            fields=[
                ('id',            models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('room_name',     models.CharField(max_length=100, unique=True)),
                ('provider_id',   models.UUIDField(blank=True, null=True)),
                ('provider_name', models.CharField(blank=True, max_length=200)),
                ('subject',       models.CharField(blank=True, max_length=200)),
                ('status',        models.CharField(
                    choices=[('pending','Pending'),('active','Active'),('ended','Ended'),('missed','Missed')],
                    default='pending', max_length=10)),
                ('started_at',    models.DateTimeField(auto_now_add=True)),
                ('joined_at',     models.DateTimeField(blank=True, null=True)),
                ('ended_at',      models.DateTimeField(blank=True, null=True)),
                ('initiator',     models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='initiated_video_calls',
                    to=settings.AUTH_USER_MODEL)),
                ('counterpart',   models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='received_video_calls',
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'video_calls', 'ordering': ['-started_at']},
        ),
    ]
