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

import datetime
import unittest

from backend.crossref import convert_to_name_pair
from backend.crossref import CrossRefAPI
from backend.crossref import DOI_PROXY_SUPPORTS_BATCH
from backend.crossref import fetch_dois_by_batch
from backend.crossref import fetch_dois_incrementally
from backend.crossref import fetch_metadata_by_DOI
from backend.crossref import get_publication_date
from backend.crossref import is_oa_license
from backend.crossref import parse_crossref_date
from django.test import TestCase
from papers.errors import MetadataSourceException


class CrossRefTest(TestCase):

    def setUp(self):
        self.api = CrossRefAPI()

    def test_empty_pubdate(self):
        # This DOI has an empty 'issued' date
        p = self.api.create_paper_by_doi('10.1007/978-1-4020-7884-2_13')
        self.assertEqual(p.pubdate.year, 2006)

    def test_affiliations(self):
        p = self.api.create_paper_by_doi('10.4204/eptcs.172.16')
        self.assertEqual(p.authors[0].affiliation,
                         'École Normale Supérieure, Paris')

    def test_dirty_metadata(self):
        # saving a paper with enough metadata to create a paper, but not
        # an OaiRecord.
        p = self.api.save_doi_metadata({
            "DOI": "10.1007/978-1-4020-7884-2_13",
            "subtitle": [],
            "author": [
                {
                    "affiliation": [],
                    "given": "Haowen",
                    "family": "Chan"
                },
                {
                    "affiliation": [],
                    "given": "Adrian",
                    "family": "Perrig"
                },
                {
                    "affiliation": [],
                    "given": "Dawn",
                    "family": "Song"
                }
            ],
            "created": {
                "timestamp": 1166129219000,
                "date-time": "2006-12-14T20:46:59Z",
                "date-parts": [
                    [
                        2006,
                        12,
                        14
                    ]
                ]
            },
            "title": [
                "Key Distribution Techniques for Sensor Networks"
            ],
            "type": "book-chapter"})
        self.assertTrue(p.is_orphan())
        self.assertFalse(p.visible)

    def test_doctype_book(self):
        # Books are ignored
        # (technically, that's because we currently require a
        # 'container-title' in the metadata)
        p = self.api.create_paper_by_doi('10.1385/1592597998')
        self.assertTrue(p.is_orphan())

    def test_doi_open(self):
        self.assertTrue(self.api.create_paper_by_doi('10.15200/winn.145838.88372').pdf_url)
        self.assertFalse(self.api.create_paper_by_doi('10.5061/dryad.b167g').pdf_url)

    def test_fetch_papers(self):
        generator = self.api.fetch_all_records(filters={'issn':'0302-9743'})
        for i in range(30):
            metadata = next(generator)
            self.assertTrue(metadata['DOI'].startswith('10.1007/'))

class CrossRefUnitTest(unittest.TestCase):

    def test_fetch_single_doi(self):
        doi = '10.5380/dp.v1i1.1922'
        metadata = fetch_metadata_by_DOI(doi)
        self.assertEqual(metadata,
                         {'publisher': 'Universidade Federal do Parana',
                          'DOI': '10.5380/dp.v1i1.1922',
                          'subtitle': [],
                          'author': [{'given': 'Frederic', 'family': 'Worms'}],
                          'URL': 'http://dx.doi.org/10.5380/dp.v1i1.1922',
                          'issued': {'date-parts': [[2005, 3, 18]]},
                          'reference-count': 0,
                          'title': 'A concep\xe7\xe3o bergsoniana do tempo',
                          'volume': '1',
                          'source': 'CrossRef',
                          'prefix': 'http://id.crossref.org/prefix/10.5380',
                          'score': 1.0,
                          'deposited': {'timestamp': 1421107200000, 'date-parts': [[2015, 1, 13]]},
                          'type': 'journal-article',
                          'container-title': 'DoisPontos',
                          'indexed': {'timestamp': 1421405831942, 'date-parts': [[2015, 1, 16]]},
                          'issue': '1',
                          'ISSN': ['2179-7412', '1807-3883'],
                          'member': 'http://id.crossref.org/member/3785'})

    def test_parse_crossref_date_incomplete(self):
        self.assertEqual(parse_crossref_date(None), None)
        self.assertEqual(
                parse_crossref_date({'date-parts': [[2015, 07, 06]]}),
                datetime.date(year=2015, month=07, day=06))
        self.assertEqual(
                parse_crossref_date({'date-parts': [[2015, 07]]}),
                datetime.date(year=2015, month=07, day=01))
        self.assertEqual(
                parse_crossref_date({'date-parts': [[2015]]}),
                datetime.date(year=2015, month=01, day=01))

    def test_parse_crossref_date_raw(self):
        self.assertEqual(
                parse_crossref_date({'raw': '2015'}),
                datetime.date(year=2015, month=01, day=01))
        self.assertEqual(
                parse_crossref_date({'raw': '2015-07'}),
                datetime.date(year=2015, month=07, day=01))
        self.assertEqual(
                parse_crossref_date({'raw': '2015-07-06'}),
                datetime.date(year=2015, month=07, day=06))

    def test_get_publication_date(self):
        self.assertEqual(
                get_publication_date(
                    fetch_metadata_by_DOI('10.5281/zenodo.18898')),
                datetime.date(year=2015, month=01, day=01))
        self.assertEqual(
                get_publication_date(
                    fetch_metadata_by_DOI('10.5380/dp.v1i1.1919')),
                datetime.date(year=2005, month=03, day=18))

    def test_batch_queries(self):
        dois = [
            '10.1007/978-3-540-46375-7_2',
            '10.1007/978-3-540-46375-7_9',
            '10.2307/2540916',
            '10.1016/s1169-8330(00)80059-9',
            '10.1017/s0022112009008003',
            '10.1051/proc/2011014',
            '10.1016/0169-5983(88)90079-2',
            '10.1080/14685240600601061',
            '10.1103/physreve.79.026303',
            '10.1103/physreve.66.046307',
            '10.1103/physrevlett.95.244502',
            '10.1017/s0022112089002351',
            '10.1063/1.4738850',
            '10.1103/physrevlett.87.054501',
            '10.1080/14685248.2012.711476',
            '10.1007/978-94-011-4177-2_12',
            '10.1007/978-1-4615-4697-9_2',
            '10.1007/978-1-4612-0137-3_7',
            '10.1007/978-1-4020-6472-2_35']
        incremental = list(fetch_dois_incrementally(dois))
        self.assertEqual(len(incremental), len(dois))
        if DOI_PROXY_SUPPORTS_BATCH:
            batch = fetch_dois_by_batch(dois)
            self.assertEqual([item['DOI'] for item in incremental],
                             [item['DOI'] for item in batch])

    def test_dirty_batches(self):
        with self.assertRaises(MetadataSourceException):
            fetch_dois_by_batch(['aunirestauniecb898989']
                                )  # definitely not a DOI

        dois = ['10.5281/anuirsetacesecesrbl']  # probably not a DOI
        results = fetch_dois_by_batch(dois)
        self.assertTrue(all([item is None for item in results]))

    def test_mixed_queries(self):
        dois = [
            '10.1016/0169-5983(88)90079-2',  # CrossRef DOI
            '10.5281/zenodo.12826',  # DataCite DOI
            ]
        results = fetch_dois_by_batch(dois)
        self.assertEqual([item['DOI'] for item in results], dois)

    def test_convert_to_name_pair(self):
        self.assertEqual(
                convert_to_name_pair({'family': 'Farge', 'given': 'Marie'}),
                ('Marie', 'Farge'))
        self.assertEqual(
                convert_to_name_pair({'literal': 'Marie Farge'}),
                ('Marie', 'Farge'))
        self.assertEqual(
                convert_to_name_pair({'literal': 'Farge, Marie'}),
                ('Marie', 'Farge'))
        self.assertEqual(
                convert_to_name_pair({'family': 'Arvind'}),
                ('', 'Arvind'))

    def test_is_oa_license(self):
        # Creative Commons licenses
        self.assertTrue(is_oa_license(
            'http://creativecommons.org/licenses/by-nc-nd/2.5/co/'))
        self.assertTrue(is_oa_license(
            'http://creativecommons.org/licenses/by-nc/3.10/'))
        self.assertTrue(is_oa_license(
            'https://creativecommons.org/licenses/by-nc-sa/4.0/'))
        # Other open licenses
        self.assertTrue(is_oa_license(
            'http://www.elsevier.com/open-access/userlicense/1.0/'))
        # Closed licenses
        self.assertFalse(is_oa_license(
            'http://link.aps.org/licenses/aps-default-license'))
        self.assertFalse(is_oa_license(
            'http://www.acs.org/content/acs/en/copyright.html'))
        self.assertFalse(is_oa_license(
            'http://www.elsevier.com/tdm/userlicense/1.0/'))
