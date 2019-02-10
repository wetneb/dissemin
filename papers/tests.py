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
from datetime import date
import doctest

import django.test
from papers.baremodels import BareName
import papers.doi
from papers.models import Name
from papers.models import OaiRecord
from papers.models import OaiSource
from papers.models import Paper
from papers.models import Researcher
from papers.models import Institution

class InstitutionTest(django.test.TestCase):
    def test_valid(self):
        institution = {
            'country': 'FR',
            'name': '  Université Paris 8 ',
            'identifier': 'ringgold-23478',
        }
        i = Institution.create(institution)
        self.assertEqual(i.country.code, institution['country'])
        self.assertEqual(i.name, institution['name'].strip())
        self.assertTrue(institution['identifier'] in i.identifiers)

    def test_too_long(self):
        institution = {
            'country': 'RU',
            'identifier': None,
            'name': """
            Не знаете как вылечить туберкулез - мы вам
            подскажем, достаточно заказать азиатскую медведку и начать ее принимать.
            Способ применения достаточно прост, а эффект потрясающий. Не ждите, ведь
            завтра может быть уже поздно. Звоните по тел +796О8887578 или заходите на
            сайт http://kypit-medvedki.ru/
            """}
        # This institution is too long for our model!
        self.assertEqual(
            Institution.create(institution),
            None)

    def test_invalid_country_code(self):
        institution = {
            'country': 'XX',
            'identifier': None,
            'name': 'University of planet earth'}

        self.assertEqual(
            Institution.create(institution),
            None)


class ResearcherTest(django.test.TestCase):

    def test_creation(self):
        r = Researcher.create_by_name('Marie', 'Farge')
        r2 = Researcher.create_by_name(' Marie', ' Farge')
        self.assertNotEqual(r, r2)

        r3 = Researcher.get_or_create_by_orcid('0000-0002-4445-8625')
        self.assertNotEqual(r, r3)

    def test_empty_name(self):
        r = Researcher.create_by_name('', '')
        self.assertEqual(r, None)
        # this ORCID has no public name in the sandbox:
        r = Researcher.get_or_create_by_orcid('0000-0002-6091-2701',
            instance='sandbox.orcid.org')
        self.assertEqual(r, None)

    def test_institution(self):
        r = Researcher.get_or_create_by_orcid('0000-0002-0022-2290',
            instance='sandbox.orcid.org')
        self.assertEqual(r.institution.name,
                'Ecole Normale Superieure')

    def test_institution_match(self):
        # first, load a profile from someone with
        # a disambiguated institution (from the sandbox)
        # http://sandbox.orcid.org/0000-0001-7174-97
        r = Researcher.get_or_create_by_orcid('0000-0001-7174-9738',
            instance='sandbox.orcid.org')
        # then, load someone else, with the same institution, but not
        # disambiguated, and without accents
        # http://sandbox.orcid.org//0000-0001-6068-024
        r2 = Researcher.get_or_create_by_orcid('0000-0001-6068-0245',
            instance='sandbox.orcid.org')
        self.assertEqual(r.institution, r2.institution)

    def test_refresh(self):
        r = Researcher.get_or_create_by_orcid('0000-0002-0022-2290',
                    instance='sandbox.orcid.org')
        self.assertEqual(r.institution.name, 'Ecole Normale Superieure')
        r.institution = None
        r.name = Name.lookup_name(('John','Doe'))
        r.save()
        r = Researcher.get_or_create_by_orcid('0000-0002-0022-2290',
                instance='sandbox.orcid.org',
                update=True)
        self.assertEqual(r.institution.name, 'Ecole Normale Superieure')


    def test_name_conflict(self):
        # Both are called "John Doe"
        r1 = Researcher.get_or_create_by_orcid('0000-0001-7295-1671')
        r2 = Researcher.get_or_create_by_orcid('0000-0001-5393-1421')
        self.assertNotEqual(r1, r2)


class NameTest(django.test.TestCase):
    def test_max_length(self):
        # The long string is shorter than the max name length,
        # but becomes longer after escaping of the & sign
        self.assertEqual(
            Name.lookup_name(("""
an ISO 9001 Certified Instrumentation
Company in India manufactures hi-tech Calibration Instruments & Systems
for Pressure, Temperature & Electrical parameters. Many of our
Temperature & Pressure Calibrator Models are Certified by DNV. Nagman
also""", "Nagman")),
            None)

class OaiRecordTest(django.test.TestCase):

    @classmethod
    def setUpClass(self):
        super(OaiRecordTest, self).setUpClass()
        self.source = OaiSource.objects.get_or_create(identifier='arxiv',
                                                      defaults={'name': 'arXiv', 'oa': False, 'priority': 1, 'default_pubtype': 'preprint'})

    def test_find_duplicate_records_invalid_url(self):
        paper = Paper.get_or_create('this is a title', [Name.lookup_name(('Jean', 'Saisrien'))],
                                    datetime.date(year=2015, month=05, day=04))
        # This used to throw an exception
        OaiRecord.find_duplicate_records(
            paper, 'ftp://dissem.in/paper.pdf', None)


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(papers.doi))
    return tests


class PaperTest(django.test.TestCase):

    @classmethod
    def setUpClass(self):
        super(PaperTest, self).setUpClass()

    def test_create_by_doi(self):
        # we recapitalize the DOI to make sure it is treated in a
        # case-insensitive way internally
        p = Paper.create_by_doi('10.1109/sYnAsc.2010.88')
        p = Paper.from_bare(p)
        self.assertEqual(
            p.title, 'Monitoring and Support of Unreliable Services')
        self.assertEqual(p.publications[0].doi, '10.1109/synasc.2010.88')

    def test_create_by_identifier(self):
        # Paper has no date
        p = Paper.create_by_oai_id('ftciteseerx:oai:CiteSeerX.psu:10.1.1.487.869')
        self.assertEqual(p, None)
        # Valid paper
        p = Paper.create_by_oai_id('ftpubmed:oai:pubmedcentral.nih.gov:4131942')
        self.assertEqual(p.pdf_url, 'http://www.ncbi.nlm.nih.gov/pubmed/24806729')

    def test_create_by_hal_id(self):
        p = Paper.create_by_hal_id('hal-00830421')
        self.assertEqual(p.oairecords[0].splash_url, 'http://hal.archives-ouvertes.fr/hal-00830421')

    def test_publication_pdf_url(self):
        # This paper is gold OA
        p = Paper.create_by_doi('10.1007/BF02702259')
        p = Paper.from_bare(p)
        # so the pdf_url of the publication should be set
        self.assertEqual(p.publications[0].pdf_url.lower(
            ), 'http://dx.doi.org/10.1007/BF02702259'.lower())

    def test_create_no_authors(self):
        p = Paper.create_by_doi('10.1021/cen-v043n050.p033')
        self.assertNotEqual(p, None)
        self.assertEqual(p.title, 'Chlorine Expansion Builds Up Steam')

    def test_create_invalid_doi(self):
        p = Paper.create_by_doi('10.1021/eiaeuiebop134223cen-v043n050.p033')
        self.assertEqual(p, None)

    def test_merge(self):
        # Get a paper with CrossRef metadata
        p = Paper.create_by_doi('10.1111/j.1744-6570.1953.tb01038.x')
        p = Paper.from_bare(p)
        # Create a copy with slight variations
        names = [BareName.create_bare(f, l) for (f, l) in
                 [('M. H.', 'Jones'), ('R. H.', 'Haase'), ('S. F.', 'Hulbert')]]
        p2 = Paper.get_or_create(
                'A Survey of the Literature on Technical Positions', names,
                date(year=2011, month=01, day=01))
        # The two are not merged because of the difference in the title
        self.assertNotEqual(p, p2)
        # Fix the title of the second one
        p2.title = 'A Survey of the Literature on Job Analysis of Technical Positions'
        p2.save()
        # Check that the new fingerprint is equal to that of the first paper
        self.assertEqual(p2.new_fingerprint(), p.fingerprint)
        # and that the new fingerprint and the current differ
        self.assertNotEqual(p2.new_fingerprint(), p2.fingerprint)
        # and that the first paper matches its own shit
        self.assertEqual(Paper.objects.filter(
            fingerprint=p.fingerprint).first(), p)
        # The two papers should hence be merged together
        new_paper = p2.recompute_fingerprint_and_merge_if_needed()
        self.assertEqual(new_paper.pk, p.pk)

    def test_attributions_preserved_by_merge(self):
        p1 = Paper.create_by_doi('10.4049/jimmunol.167.12.6786')
        r1 = Researcher.create_by_name('Stephan', 'Hauschildt')
        p1.set_researcher(4, r1.id)
        p2 = Paper.create_by_doi('10.1016/j.chemgeo.2015.03.025')
        r2 = Researcher.create_by_name('Priscille', 'Lesne')
        p2.set_researcher(0, r2.id)

        # merge them ! even if they actually don't have anything
        # to do together
        p1.merge(p2)

        p1.check_authors()

        self.assertEqual(p1.researchers,
                         [r2, r1])

    def test_set_researcher(self):
        p1 = Paper.create_by_doi('10.4049/jimmunol.167.12.6786')
        r1 = Researcher.create_by_name('Stephan', 'Hauschildt')
        # Add the researcher
        p1.set_researcher(4, r1.id)
        self.assertEqual(set(p1.researchers), {r1})
        # Remove the researcher
        p1.set_researcher(4, None)
        self.assertEqual(set(p1.researchers), set())
