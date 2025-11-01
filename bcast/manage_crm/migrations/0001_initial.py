# ==========================================
# FILE: manage_crm/migrations/0001_initial.py
# ==========================================
"""
Initial CRM models migration
"""

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('manage_organization', '0002_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CRMSyncLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('django_id', models.IntegerField()),
                ('frappe_id', models.CharField(max_length=255)),
                ('doctype', models.CharField(choices=[('Contact', 'Contact'), ('User', 'User'), ('Lead', 'Lead'), ('Issue', 'Issue')], max_length=50)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('success', 'Success'), ('failed', 'Failed'), ('partial', 'Partial')], max_length=20)),
                ('details', models.TextField(blank=True, null=True)),
                ('synced_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='crm_sync_logs', to='manage_organization.organization')),
            ],
            options={
                'ordering': ['-synced_at'],
            },
        ),
        migrations.CreateModel(
            name='CRMSyncConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('auto_sync_contacts', models.BooleanField(default=True)),
                ('auto_sync_employees', models.BooleanField(default=True)),
                ('auto_sync_conversations', models.BooleanField(default=False)),
                ('last_contact_sync', models.DateTimeField(blank=True, null=True)),
                ('last_employee_sync', models.DateTimeField(blank=True, null=True)),
                ('is_syncing', models.BooleanField(default=False)),
                ('sync_error', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organization', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='crm_sync_config', to='manage_organization.organization')),
            ],
        ),
        migrations.AddIndex(
            model_name='crmsynclog',
            index=models.Index(fields=['organization', 'status'], name='manage_crm_crm_synclog_index_1'),
        ),
        migrations.AddIndex(
            model_name='crmsynclog',
            index=models.Index(fields=['django_id', 'doctype'], name='manage_crm_crm_synclog_index_2'),
        ),
        migrations.AddIndex(
            model_name='crmsynclog',
            index=models.Index(fields=['frappe_id'], name='manage_crm_crm_synclog_index_3'),
        ),
    ]
