# -*- coding: utf-8 -*-


from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('papers', '0001_squashed_0059_remove_django_geojson'),
        ('deposit', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Repository',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=64)),
                ('description', models.TextField()),
                ('logo', models.ImageField(upload_to='repository_logos/')),
                ('protocol', models.CharField(max_length=32)),
                ('username', models.CharField(max_length=64, null=True, blank=True)),
                ('password', models.CharField(max_length=128, null=True, blank=True)),
                ('api_key', models.CharField(max_length=256, null=True, blank=True)),
                ('endpoint', models.CharField(max_length=256, null=True, blank=True)),
                ('oaisource', models.ForeignKey(to='papers.OaiSource', on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
