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




import unittest
import json
import requests
import os

from papers.orcid import OrcidProfile
from papers.orcid import OrcidWorkSummary
from papers.orcid import OrcidWork

class OrcidProfileStub(OrcidProfile):
    def __init__(self, orcid_id, instance='orcid.org'):
        super(OrcidProfileStub, self).__init__(orcid_id=orcid_id, instance=instance,
              json=self.request_or_load(orcid_id, instance))

    @classmethod
    def request_or_load(cls, path, instance):
        url = 'https://pub.{instance}/v2.1/{path}'.format(instance=instance, path=path)
        full_path = 'papers/fixtures/orcid/{}.json'.format(path.replace('/','-'))
        try:
            with open(full_path, 'r') as f:
                response = json.load(f)
            return response
        except Exception as e:
            print(e)
            r = requests.get(url,headers={'Accept':'application/json'})
            j = r.json()
            print(r.json())
            with open(full_path, 'w') as f:
                f.write(json.dumps(j))
            return j


    def request_element(self, path):
        return self.request_or_load(self.id + '/'+ path, self.instance)

class OrcidProfileTest(unittest.TestCase):

    @classmethod
    def loadProfile(cls, id):
        return OrcidProfileStub(id)

    @classmethod
    def setUpClass(self):
        self.antonin = self.loadProfile(id='0000-0002-8612-8827')
        self.thomas = self.loadProfile(id='0000-0003-0524-631X')
        self.sergey = self.loadProfile(id='0000-0003-3397-9895')
        self.marco = self.loadProfile(id='0000-0002-6561-5642')

    def test_simple_name(self):
        self.assertEqual(self.antonin.name, ('Antonin', 'Delpeuch'))
        self.assertEqual(self.thomas.name, ('Thomas', 'Bourgeat'))
        self.assertEqual(self.marco.name, ('Marco', 'Diana'))

    def test_credit_name(self):
        self.assertEqual(self.sergey.name, ('Sergey M.', 'Natanzon'))
        self.assertEqual(self.loadProfile(id='0000-0001-9547-293X').name, ('Darío', 'Álvarez'))

    def test_empty_lastname(self):
        self.assertEqual(self.loadProfile(id='0000-0001-5006-3868').name, ('Qiang', ''))

    def test_other_names(self):
        self.assertEqual(set(self.sergey.other_names),
                         set([('Sergey', 'Natanzon'), ('S.', 'Natanzon'),
                              ('S. M.', 'Natanzon'), ('Sergey', 'Natanzon')]))

    def test_homepage_without_http(self):
        self.assertEqual(self.loadProfile(
            id='0000-0002-5710-3989').homepage, 'http://evrard.perso.enseeiht.fr')

    def test_iterable(self):
        for key in self.thomas:
            self.assertEqual(type(key), str)

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

    def test_institution(self):
        self.assertEqual(self.loadProfile(
            id='0000-0002-0022-2290').institution,
            {'name':'Ecole Normale Superieure',
             'identifier':None,
             'country':'FR'})
        self.assertEqual(self.loadProfile(
            id='0000-0002-5654-4053').institution,
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

    def test_philipp(self):
        p = self.loadProfile(id='0000-0001-6723-6833')

        summaries = p.work_summaries
        dois = [summary.doi for summary in summaries]
        self.assertTrue('10.3354/meps09890' in dois)

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

    def test_multiple_ids(self):
        summary_json = {
            "last-modified-date" : {
            "value" : 1506388112650
            },
            "external-ids" : {
            "external-id" : [ {
                "external-id-type" : "eid",
                "external-id-value" : "2-s2.0-84864877237",
                "external-id-url" : None,
                "external-id-relationship" : "SELF"
            }, {
                "external-id-type" : "doi",
                "external-id-value" : "10.3354/meps09890",
                "external-id-url" : None,
                "external-id-relationship" : "SELF"
            } ]
            },
            "work-summary" : [ {
            "put-code" : 19176128,
            "created-date" : {
                "value" : 1444695659490
            },
            "last-modified-date" : {
                "value" : 1506388112650
            },
            "source" : {
                "source-orcid" : None,
                "source-client-id" : {
                "uri" : "https://orcid.org/client/0000-0002-3054-1567",
                "path" : "0000-0002-3054-1567",
                "host" : "orcid.org"
                },
                "source-name" : {
                "value" : "CrossRef Metadata Search"
                }
            },
            "title" : {
                "title" : {
                "value" : "Elephant seal foraging dives track prey distribution, not temperature: Comment on McIntyre et al. (2011)"
                },
                "subtitle" : None,
                "translated-title" : None
            },
            "external-ids" : {
                "external-id" : [ {
                "external-id-type" : "doi",
                "external-id-value" : "10.3354/meps09890",
                "external-id-url" : None,
                "external-id-relationship" : "SELF"
                } ]
            },
            "type" : "JOURNAL_ARTICLE",
            "publication-date" : {
                "year" : {
                "value" : "2012"
                },
                "month" : {
                "value" : "08"
                },
                "day" : {
                "value" : "08"
                },
                "media-type" : None
            },
            "visibility" : "PUBLIC",
            "path" : "/0000-0001-6723-6833/work/19176128",
            "display-index" : "0"
            }]}
        summary = OrcidWorkSummary(summary_json)
        self.assertEqual(summary.doi, '10.3354/meps09890')

    def test_works(self):
        summaries = self.antonin.work_summaries
        put_codes = [s.put_code for s in summaries]
        works = list(self.antonin.fetch_works(put_codes))
        titles = [work.title for work in works]
        self.assertTrue('Complexity of Grammar Induction for Quantum Types' in titles)
        pubtypes = [work.pubtype for work in works]
        self.assertTrue('journal-article' in pubtypes)


class OrcidWorkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.testdir = os.path.dirname(os.path.abspath(__file__))

    def load_work(self, orcid_id, filename):
        profile = OrcidProfileStub(orcid_id)
        with open(os.path.join(self.testdir, 'data', filename), 'r') as f:
            return OrcidWork(profile, json_representation=json.load(f))

    def test_authors_from_bibtex(self):
        work = self.load_work('0000-0003-2888-1770', 'Negation_of_graded_beliefs.json')
        self.assertEqual([('Bénédicte', 'Legastelois'), ('Marie-Jeanne', 'Lesot'),('Adrien', "Revault d'Allonnes")], work.authors)

    def test_put_code(self):
        work = self.load_work('0000-0003-2888-1770', 'Vertex-centred_Method_to_Detect_Communities_in_Evolving_Networks.json')
        self.assertEqual(work.put_code, 55549876)
        self.assertEqual(work.api_uri, "https://pub.orcid.org/v2.1/0000-0003-2888-1770/work/55549876")

