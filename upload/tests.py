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


from __future__ import unicode_literals

import os
import unittest

from django.conf import settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from papers.testajax import JsonRenderingTest
from upload.models import THUMBNAIL_MAX_WIDTH
from upload.views import make_thumbnail
import wand.image as image


class ThumbnailTest(unittest.TestCase):

    def thumbnail(self, fname):
        with open(fname, 'r') as f:
            pdf = f.read()
        ret = make_thumbnail(pdf)
        if ret is not None:
            pages, thumb = ret
            self.assertIsInstance(pages, int)
            return thumb

    def assertValidPng(self, png):
        img = image.Image(blob=png)
        self.assertEqual(img.format, 'PNG')
        self.assertTrue(img.width <= 2*THUMBNAIL_MAX_WIDTH)

    def test_valid_pdf(self):
        self.assertValidPng(self.thumbnail('mediatest/blank.pdf'))

    def test_invalid_pdf(self):
        self.assertEqual(self.thumbnail('mediatest/invalid.pdf'), None)

    def test_empty_pdf(self):
        self.assertEqual(self.thumbnail('mediatest/empty.pdf'), None)

    @unittest.expectedFailure
    def test_wrong_file_format(self):
        self.assertEqual(self.thumbnail('mediatest/red-circle.png'), None)


class UploadTest(JsonRenderingTest):

    @classmethod
    def setUpClass(self):
        super(UploadTest, self).setUpClass()
        settings.MEDIA_ROOT = os.path.join(os.getcwd(), 'mediatest')
        User.objects.create_user('john', 'john@google.com', 'doe')

    def setUp(self):
        self.client.login(username='john', password='doe')

    def upload(self, fname):
        with open(fname, 'r') as f:
            return self.ajaxPost(reverse('ajax-uploadFulltext'), {'upl': f})

    def download(self, url):
        return self.ajaxPost(reverse('ajax-downloadUrl'), {'url': url})

    def test_check_method(self):
        resp = self.ajaxGet(reverse('ajax-uploadFulltext'))
        self.assertEqual(resp.status_code, 405)

    def test_logged_out(self):
        self.client.logout()
        resp = self.upload('mediatest/blank.pdf')
        self.assertEqual(resp.status_code, 302)

    def test_valid_upload(self):
        resp = self.upload('mediatest/blank.pdf')
        self.assertEqual(resp.status_code, 200)

    def test_invalid_format(self):
        resp = self.upload('mediatest/invalid.pdf')
        self.assertEqual(resp.status_code, 403)

    def test_download_nohttps(self):
        resp = self.download('http://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.696.3395&rep=rep1&type=pdf')
        self.assertEqual(resp.status_code, 200)

    def test_download(self):
        resp = self.download('http://arxiv.org/pdf/1410.1454v2')
        self.assertEqual(resp.status_code, 200)

    def test_html_download(self):
        resp = self.download('http://httpbin.org/')
        self.assertEqual(resp.status_code, 403)

    def test_loggedout_download(self):
        self.client.logout()
        resp = self.download('http://arxiv.org/pdf/1410.1454v2')
        self.assertEqual(resp.status_code, 302)

    def test_invalid_url(self):
        self.download('ttp://dissem.in')

    def test_notfound_url(self):
        resp = self.download('http://httpbin.org/ainrsetcs')
        self.assertEqual(resp.status_code, 403)

    def test_timeout(self):
        resp = self.download('https://httpbin.org/delay/20')
        self.assertEqual(resp.status_code, 403)
