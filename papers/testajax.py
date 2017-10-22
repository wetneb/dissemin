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

import json

from backend.tests import PrefilledTest
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
import django.test
import unittest
from papers.models import Paper


# TODO TO BE TESTED
# urlpatterns = patterns('',
##    url(r'^annotate-paper-(?P<pk>\d+)-(?P<status>\d+)$', annotatePaper, name='ajax-annotatePaper'),
##    url(r'^delete-researcher-(?P<pk>\d+)$', deleteResearcher, name='ajax-deleteResearcher'),
#    url(r'^add-researcher$', addResearcher, name='ajax-addResearcher'),
#    url(r'^change-publisher-status$', changePublisherStatus, name='ajax-changePublisherStatus'),
##    url(r'^harvesting-status-(?P<pk>\d+)$', harvestingStatus, name='ajax-harvestingStatus'),
#    url(r'^wait-for-consolidated-field$', waitForConsolidatedField, name='ajax-waitForConsolidatedField'),
#)


class JsonRenderingTest(PrefilledTest):

    @classmethod
    def setUpClass(self):
        super(JsonRenderingTest, self).setUpClass()
        self.client = django.test.Client()

    def checkJson(self, resp, expected_status=200):
        if resp.status_code != expected_status:
            print("Invalid status code %d, response was:\n%s" %
                (status_code, resp.content))
        self.assertEqual(resp.status_code, expected_status)
        parsed = json.loads(resp.content)
        return parsed

    def ajaxGet(self, *args, **kwargs):
        kwargs['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
        kwargs['CONTENT_TYPE'] = 'application/json'
        return self.client.get(*args, **kwargs)

    def ajaxPost(self, *args, **kwargs):
        kwargs['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
        return self.client.post(*args, **kwargs)

    def getPage(self, *args, **kwargs):
        urlargs = kwargs.copy()
        if 'getargs' in kwargs:
            del urlargs['getargs']
            return self.ajaxGet(reverse(*args, **urlargs), kwargs['getargs'])
        return self.ajaxGet(reverse(*args, **kwargs))

    def postPage(self, *args, **kwargs):
        urlargs = kwargs.copy()
        del urlargs['postargs']
        if 'postkwargs' in urlargs:
            del urlargs['postkwargs']
        return self.ajaxPost(reverse(*args, **urlargs), kwargs['postargs'], **kwargs.get('postkwargs', {}))


class PaperAjaxTest(JsonRenderingTest):

    @classmethod
    def setUpClass(cls):
        super(PaperAjaxTest, cls).setUpClass()
        u = User.objects.create_user('terry', 'pit@mat.io', 'yo')
        u.save()

    def test_researcher_papers(self):
        page = self.getPage('researcher',
                            kwargs={'researcher': self.r1.id,
                                    'slug': self.r1.slug})
        self.checkJson(page)

    @unittest.expectedFailure
    def test_consolidate_paper(self):
        p = Paper.create_by_doi('10.1175/jas-d-15-0240.1')
        self.client.login(username='terry', password='yo')
        result = self.checkJson(self.getPage(
                'ajax-waitForConsolidatedField', getargs={
                    'field': 'abstract',
                    'id': p.id}))
        self.client.logout()
        self.assertTrue(result['success'])
        self.assertTrue(len(result['value']) > 10)

    @unittest.expectedFailure
    def test_consolidate_elsevier_paper(self):
        p = Paper.create_by_doi('10.1016/0168-5597(91)90120-m')
        self.client.login(username='terry', password='yo')
        result = self.checkJson(self.getPage(
                'ajax-waitForConsolidatedField', getargs={
                    'field': 'abstract',
                    'id': p.id}))
        self.client.logout()
        self.assertTrue(result['success'])
        self.assertTrue(len(result['value']) > 10)

class PublisherAjaxTest(JsonRenderingTest):

    @classmethod
    def setUpClass(cls):
        super(PublisherAjaxTest, cls).setUpClass()
        u = User.objects.create_user('patrick', 'pat@mat.io', 'yo')
        u.is_superuser = True
        u.save()

    def setUp(self):
        super(PublisherAjaxTest, self).setUp()
        self.papers = map(Paper.create_by_doi,
                          ['10.1038/526052a', '10.1038/nchem.1829', '10.1038/nchem.1365'])
        self.publisher = self.papers[0].publications[0].publisher
        self.assertEqual(self.publisher.name, 'Nature Publishing Group')

    def test_logged_out(self):
        self.client.logout()
        req = self.postPage('ajax-changePublisherStatus',
                            postargs={'pk': self.publisher.pk, 'status': 'OA'})
        self.assertEqual(req.status_code, 302)

    def test_change_publisher_status(self):
        self.client.login(username='patrick', password='yo')
        p = self.postPage('ajax-changePublisherStatus',
                          postargs={'pk': self.publisher.pk,
                                    'status': 'OA'})
        self.assertEqual(p.status_code, 200)
        papers = [Paper.objects.get(pk=paper.pk) for paper in self.papers]
        self.assertTrue(all([paper.oa_status == 'OA' for paper in papers]))
