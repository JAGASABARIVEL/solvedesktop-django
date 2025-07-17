from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('manage_contact', '0001_initial'),
        ('manage_organization', '0004_alter_organization_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ContactCustomField',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('key', models.SlugField(max_length=100)),
                ('field_type', models.CharField(choices=[
                    ('text', 'Text'),
                    ('number', 'Number'),
                    ('dropdown', 'Dropdown'),
                    ('checkbox', 'Checkbox'),
                    ('date', 'Date')
                ], max_length=20)),
                ('options', models.JSONField(blank=True, null=True)),
                ('required', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='contact_custom_fields',
                    to='manage_organization.organization')),
            ],
            options={
                'unique_together': {('organization', 'key')},
            },
        ),
        migrations.CreateModel(
            name='ContactCustomFieldValue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('value', models.TextField(blank=True, null=True)),
                ('contact', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='custom_field_values',
                    to='manage_contact.contact')),
                ('custom_field', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='manage_contact.contactcustomfield')),
            ],
            options={
                'unique_together': {('contact', 'custom_field')},
            },
        ),
    ]

