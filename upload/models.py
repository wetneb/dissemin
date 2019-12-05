# -*- encoding: utf-8 -*-

# Dissemin: open access policy enforcement tool
# Copyright (C) 2014 Antonin Delpeuch
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Affero General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

import os

from secrets import token_urlsafe

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse

MAX_ORIG_NAME_LENGTH = 1024
THUMBNAIL_MAX_HEIGHT = 297/2
THUMBNAIL_MAX_WIDTH = 210/2


def new_urlsafe_token():
    """
    :returns: Token of length 64
    """
    return token_urlsafe(64)[:64]


class UploadedPDF(models.Model):
    """
    A PDF file, plus some useful info about who/when/how it was uploaded.
    """

    #: The user who uploaded that file
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    #: When it was uploaded
    timestamp = models.DateTimeField(auto_now=True)
    #: How it was uploaded: either filename or URL
    orig_name = models.CharField(max_length=MAX_ORIG_NAME_LENGTH)
    #: Number of pages
    num_pages = models.IntegerField(default=0)
    #: secret token to expose file by credential
    token = models.CharField(max_length=64, default=new_urlsafe_token)

    #: The file itself
    file = models.FileField(upload_to='uploads/%Y/%m/%d')
    #: A thumbnail of the first page
    thumbnail = models.FileField(upload_to='thumbnails/')

    class Meta:
        verbose_name = 'Uploaded PDF'

    def get_absolute_url(self):
        """
        Returns the url to object
        :returns: object url
        """
        return reverse('file-download', args=[self.pk, self.token])

    @property
    def absolute_path(self):
        """
        Returns the full path to the file as property
        :returns: full path to file
        """
        return os.path.join(settings.MEDIA_ROOT, self.file.name)
