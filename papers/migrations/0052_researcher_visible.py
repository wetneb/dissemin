# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2018-10-21 09:28
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('papers', '0051_alter_last_update'),
    ]

    operations = [
        migrations.AddField(
            model_name='researcher',
            name='visible',
            field=models.BooleanField(default=True),
        ),
    ]
