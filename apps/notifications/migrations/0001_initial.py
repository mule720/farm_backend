import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id',         models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title',      models.CharField(max_length=200)),
                ('message',    models.TextField()),
                ('category',   models.CharField(
                    choices=[
                        ('alert','Alert'),('automation','Automation'),('weather','Weather'),
                        ('kpi','KPI'),('irrigation','Irrigation'),('livestock','Livestock'),
                        ('equipment','Equipment'),('financial','Financial'),('labor','Labour'),
                        ('inventory','Inventory'),('market','Market'),('compliance','Compliance'),
                        ('vision','AI Vision'),('system','System'),
                    ],
                    default='system', max_length=30,
                )),
                ('priority',   models.CharField(
                    choices=[('critical','Critical'),('warning','Warning'),('info','Info')],
                    default='info', max_length=10,
                )),
                ('is_read',    models.BooleanField(default=False)),
                ('read_at',    models.DateTimeField(blank=True, null=True)),
                ('action_url', models.CharField(blank=True, max_length=200)),
                ('ref_id',     models.CharField(blank=True, max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('recipient',  models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notifications',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'db_table': 'notifications', 'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['recipient', 'is_read', '-created_at'], name='notif_recip_unread_idx'),
        ),
    ]
