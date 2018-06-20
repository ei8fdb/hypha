# Generated by Django 2.0.2 on 2018-06-21 09:31

import django.contrib.postgres.fields.jsonb
import django.core.serializers.json
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('funds', '0033_use_django_fsm'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApplicationRevision',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('form_data', django.contrib.postgres.fields.jsonb.JSONField(encoder=django.core.serializers.json.DjangoJSONEncoder)),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='revisions', to='funds.ApplicationSubmission')),
            ],
        ),
        migrations.AddField(
            model_name='applicationsubmission',
            name='draft_revision',
            field=models.OneToOneField(editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='draft', to='funds.ApplicationRevision'),
        ),
        migrations.AddField(
            model_name='applicationsubmission',
            name='live_revision',
            field=models.OneToOneField(editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='live', to='funds.ApplicationRevision'),
        ),
    ]
