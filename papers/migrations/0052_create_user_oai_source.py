# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

def populate_oai_sources(apps, schema_editor):
    OaiSource = apps.get_model('papers', 'OaiSource')

    oai_sources = [
        ('user_provided', 'User providded', False, 100, 'preprint'),
        ]

    # Auto-create all the Oai Sources when this module is imported
    for identifier, name, oa, priority, pubtype in oai_sources:
        OaiSource.objects.get_or_create(
            identifier=identifier,
            defaults={'name': name,
                      'oa': oa,
                      'priority': priority,
                      'default_pubtype': pubtype})

def do_nothing(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('papers', '0051_alter_last_update'),
    ]

    operations = [
        migrations.RunPython(populate_oai_sources, do_nothing)
    ]


