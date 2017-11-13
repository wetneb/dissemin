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

import unittest

from papers.orcid import OrcidProfile
from papers.orcid import OrcidWorkSummary

class OrcidProfileTest(unittest.TestCase):
    """
    TODO: duplicate all these profiles to the ORCID sandbox
    to be sure they will not be modified!
    """

    @classmethod
    def setUpClass(self):
        self.antonin = OrcidProfile(orcid_id='0000-0002-8612-8827')
        self.thomas = OrcidProfile(orcid_id='0000-0003-0524-631X')
        self.sergey = OrcidProfile(orcid_id='0000-0003-3397-9895')
        self.marco = OrcidProfile(orcid_id='0000-0002-6561-5642')

    def test_simple_name(self):
        self.assertEqual(self.antonin.name, ('Antonin', 'Delpeuch'))
        self.assertEqual(self.thomas.name, ('Thomas', 'Bourgeat'))
        self.assertEqual(self.marco.name, ('Marco', 'Diana'))

    def test_credit_name(self):
        self.assertEqual(self.sergey.name, ('Sergey M.', 'Natanzon'))
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0001-9547-293X').name, ('Darío', 'Álvarez'))

    def test_empty_lastname(self):
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0001-5006-3868').name, ('Qiang', ''))

    def test_other_names(self):
        self.assertEqual(set(self.sergey.other_names),
                         set([('Sergey', 'Natanzon'), ('S.', 'Natanzon'),
                              ('S. M.', 'Natanzon'), ('Sergey', 'Natanzon')]))

    def test_homepage_without_http(self):
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0002-5710-3989').homepage, 'http://evrard.perso.enseeiht.fr')

    def test_iterable(self):
        for key in self.thomas:
            self.assertEqual(type(key), unicode)

    def test_attr(self):
        self.assertTrue('orcid-identifier' in self.thomas)
        self.assertEqual(type(self.thomas['orcid-identifier']), dict)

    def test_wrong_instance(self):
        with self.assertRaises(ValueError):
            p = OrcidProfile('0000-0002-2963-7764', instance='dissem.in')
            del p

    def test_sandbox(self):
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0002-5654-4053').name, ('Peter', 'Lieth'))

    def test_search(self):
        # for this one we use the production database
        # because test profiles on the sandbox
        # tend to get deleted quite often
        results = list(OrcidProfile.search_by_name('John', 'Doe'))
        self.assertTrue(all(map(lambda x: len(x['orcid']) and (
            len(x['first']) or len(x['last'])), results)))
        names_returned = map(lambda x: (x['first'], x['last']), results)
        self.assertTrue(('John', 'Doe') in names_returned)

    def test_institution(self):
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0002-0022-2290').institution,
            {'name':'Ecole Normale Superieure',
             'identifier':None,
             'country':'FR'})
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0002-5654-4053').institution,
            {'country': 'FR',
             'identifier': None,
             'name': "École nationale supérieure de céramique industrielle"})

    def test_work_summaries(self):
        summaries = self.antonin.work_summaries
        dois = [summary.doi for summary in summaries]
        titles = [summary.title for summary in summaries]
        self.assertTrue('10.4204/eptcs.172.16' in dois)
        self.assertTrue('Complexity of Grammar Induction for Quantum Types' in titles)
        self.assertTrue(None not in [summary.put_code for summary in summaries])

    def test_wrong_id_type(self):
        """
        I found this payload in an ORCID profile… looks like ORCID
        does not validate their ids against regexes
        """
        summary_json = {
            "last-modified-date" : {
            "value" : 1505077812702
            },
            "external-ids" : {
            "external-id" : [ {
                "external-id-type" : "doi",
                "external-id-value" : "http://hdl.handle.net/2080/2662",
                "external-id-url" : None,
                "external-id-relationship" : "SELF"
            } ]
            },
            "work-summary" : [ {
            "put-code" : 36669776,
            "created-date" : {
                "value" : 1505077812702
            },
            "last-modified-date" : {
                "value" : 1505077812702
            },
            "source" : {
                "source-orcid" : {
                "uri" : "https://orcid.org/0000-0002-9658-1473",
                "path" : "0000-0002-9658-1473",
                "host" : "orcid.org"
                },
                "source-client-id" : None,
                "source-name" : {
                "value" : "Bhojaraju Gunjal"
                }
            },
            "title" : {
                "title" : {
                "value" : "Open Source Solutions for Creation of ETD Archives/Repository: A Case Study of Central Library@NIT Rourkela"
                },
                "subtitle" : None,
                "translated-title" : None
            },
            "external-ids" : {
                "external-id" : [ {
                "external-id-type" : "doi",
                "external-id-value" : "http://hdl.handle.net/2080/2662",
                "external-id-url" : None,
                "external-id-relationship" : "SELF"
                } ]
            },
            "type" : "CONFERENCE_PAPER",
            "publication-date" : {
                "year" : {
                "value" : "2017"
                },
                "month" : None,
                "day" : None,
                "media-type" : None
            },
            "visibility" : "PUBLIC",
            "path" : "/0000-0002-9658-1473/work/36669776",
            "display-index" : "1"
            } ]
        }
        summary = OrcidWorkSummary(summary_json)
        self.assertEqual(summary.doi, None)


    def test_works(self):
        summaries = self.antonin.work_summaries
        put_codes = [s.put_code for s in summaries]
        works = list(self.antonin.fetch_works(put_codes))
        titles = [work.title for work in works]
        self.assertTrue('Complexity of Grammar Induction for Quantum Types' in titles)
        pubtypes = [work.pubtype for work in works]
        self.assertTrue('journal-article' in pubtypes)

