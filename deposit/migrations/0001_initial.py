# -*- coding: utf-8 -*-


from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('upload', '0002_uploadedpdf_num_pages'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('papers', '0001_squashed_0059_remove_django_geojson'),
    ]

    operations = [
        migrations.CreateModel(
            name='DepositRecord',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('request', models.TextField(null=True, blank=True)),
                ('identifier', models.CharField(max_length=512, null=True, blank=True)),
                ('pdf_url', models.URLField(max_length=1024, null=True, blank=True)),
                ('date', models.DateTimeField(auto_now=True)),
                ('upload_type', models.FileField(upload_to='deposits')),
                ('file', models.ForeignKey(to='upload.UploadedPDF', on_delete=models.CASCADE)),
                ('paper', models.ForeignKey(to='papers.Paper', on_delete=models.CASCADE)),
                ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE)),
            ],
            options={
                'db_table': 'papers_depositrecord',
            },
            bases=(models.Model,),
        ),
    ]
