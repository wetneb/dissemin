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
import re
import unittest
import requests_mock

from deposit.tests import lorem_ipsum
from deposit.tests import ProtocolTest
from deposit.zenodo.protocol import ZenodoProtocol
from papers.models import Paper
from backend.oai import get_proaixy_instance

class ZenodoProtocolTest(ProtocolTest):

    @classmethod
    def setUpClass(self):
        if 'ZENODO_SANDBOX_API_KEY' not in os.environ:
            raise unittest.SkipTest(
                "Environment variable ZENODO_SANDBOX_API_KEY is undefined")
        super(ZenodoProtocolTest, self).setUpClass()
        self.repo.api_key = os.environ['ZENODO_SANDBOX_API_KEY']
        self.repo.endpoint = 'https://sandbox.zenodo.org/api/deposit/depositions'
        self.proto = ZenodoProtocol(self.repo)

    def test_lncs(self):
        p = Paper.create_by_doi('10.1007/978-3-662-47666-6_5')
        r = self.dry_deposit(p,
            abstract = lorem_ipsum,
            license = 'zenodo-freetoread-1.0')
        self.assertEqual(r.status, 'faked')

    def test_deposit_paper_already_on_zenodo(self):
        p = get_proaixy_instance().create_paper_by_identifier(
            'ftzenodo:oai:zenodo.org:50134', 'base_dc')
        enabled = self.proto.init_deposit(p, self.user)
        self.assertFalse(enabled)

    def test_500_error(self):
        with requests_mock.Mocker(real_http=True) as mocker:
            mocker.get(re.compile('.*\.zenodo\.org/.*'), status_code=500)
            p = Paper.create_by_doi('10.1007/978-3-662-47666-6_5')
            r = self.dry_deposit(p,
                    abstract = lorem_ipsum,
                    license = 'zenodo-freetoread-1.0')
            self.assertEqual(r.status, 'failed')

