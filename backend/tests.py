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

from backend.crossref import CrossRefAPI
from backend.maintenance import cleanup_names
from backend.maintenance import cleanup_researchers
from backend.maintenance import create_publisher_aliases
from backend.maintenance import recompute_publisher_policies
from backend.maintenance import refetch_containers
from backend.maintenance import refetch_publishers
from backend.maintenance import update_paper_statuses
from backend.orcid import affiliate_author_with_orcid
from backend.orcid import OrcidPaperSource
from backend.romeo import fetch_journal
from backend.romeo import fetch_publisher
from backend.romeo import find_journal_in_model
from backend.romeo import perform_romeo_query
from backend.tasks import fetch_everything_for_researcher
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.test import override_settings
from django.test import TestCase
import haystack
from lxml import etree
from papers.baremodels import BareAuthor
from papers.baremodels import BareName
from papers.baremodels import BarePaper
from papers.models import Department
from papers.models import Institution
from papers.models import Name
from papers.models import OaiRecord
from papers.models import OaiSource
from papers.models import Paper
from papers.models import Researcher
from publishers.models import Journal

TEST_INDEX = {
    'default': {
        'ENGINE': 'search.SearchEngine',
        'URL': 'http://localhost:9200/',
        'INDEX_NAME': 'dissemin_test',
    },
}


# SHERPA/RoMEO interface
class RomeoTest(TestCase):

    def test_perform_query(self):
        self.assertIsInstance(perform_romeo_query(
            {'issn': '0022-328X'}), etree._ElementTree)
        self.assertIsInstance(perform_romeo_query(
            {'jtitle': 'Physical Review E'}), etree._ElementTree)

    def test_fetch_journal(self):
        terms = {'issn': '0022-328X'}
        orig_terms = terms.copy()
        self.assertIsInstance(fetch_journal(terms), Journal)
        self.assertEqual(terms, orig_terms)
        journal = find_journal_in_model(terms)
        self.assertIsInstance(journal, Journal)
        self.assertEqual(journal.issn, terms['issn'])

    def test_fetch_publisher(self):
        self.assertEqual(fetch_publisher(None), None)
        # TODO: more tests!

    def test_unicode(self):
        terms = {'issn': '0375-0906'}
        journal = fetch_journal(terms)
        self.assertEqual(
            journal.title, 'Revista de Gastroenterología de México')
        self.assertEqual(journal.publisher.name, 'Elsevier España')

    def test_ampersand(self):
        terms = {'issn': '0003-1305'}
        journal = fetch_journal(terms)
        self.assertEqual(journal.publisher.name, 'Taylor & Francis')

    def test_overescaped(self):
        terms = {'issn': '2310-0133'}
        journal = fetch_journal(terms)
        self.assertEqual(journal.publisher.alias,
                         'Научный издательский дом Исследов')

    def test_too_long(self):
        terms = {'jtitle': ("Volume 3: Industrial Applications; Modeling "
                            "for Oil and Gas, Control and Validation, Estimation, and Control of "
                            "Automotive Systems; Multi-Agent and Networked Systems; Control System "
                            "Design; Physical Human-Robot Interaction; "
                            "Rehabilitation Robotics; Sensing and Actuation for Control; Biomedical "
                            "Systems; Time Delay Systems and Stability; Unmanned Ground and Surface "
                            "Robotics; Vehicle Motion Controls; Vibration Analysis and Isolation; "
                            "Vibration and Control for Energy Harvesting; Wind Energy")}
        self.assertEqual(fetch_journal(terms), None)

    def test_openaccess(self):
        self.assertEqual(fetch_journal(
            {'issn': '1471-2105'}).publisher.oa_status, 'OA')
        self.assertEqual(fetch_journal(
            {'issn': '1951-6169'}).publisher.oa_status, 'OA')

    def test_closed(self):
        self.assertEqual(fetch_journal(
            {'issn': '0001-4826'}).publisher.oa_status, 'NOK')

    def test_open(self):
        self.assertEqual(fetch_journal(
            {'issn': '1631-073X'}).publisher.oa_status, 'OK')
        self.assertEqual(fetch_journal(
            {'issn': '0099-2240'}).publisher.oa_status, 'OK')
        self.assertEqual(fetch_journal(
            {'issn': '0036-8075'}).publisher.oa_status, 'OK')

# Generic test case that requires some example DB


@override_settings(HAYSTACK_CONNECTIONS=TEST_INDEX)
class PrefilledTest(TestCase):
    fixtures = ['test_dump.json']

    @classmethod
    def setUpTestData(self):
        if self is PrefilledTest:
            raise unittest.SkipTest("Base test")
        haystack.connections.reload('default')
        call_command('update_index', verbosity=0)
        self.i = Institution.objects.get(name='ENS')
        self.d = Department.objects.get(name='Chemistry dept')
        self.di = Department.objects.get(name='Comp sci dept')

        def get_by_name(first, last):
            n = Name.lookup_name((first, last))
            return Researcher.objects.get(name=n)
        self.r1 = get_by_name('Isabelle', 'Aujard')
        self.r2 = get_by_name('Ludovic', 'Jullien')
        self.r3 = get_by_name('Antoine', 'Amarilli')
        self.r4 = get_by_name('Antonin', 'Delpeuch')
        self.r5 = get_by_name('Terence', 'Tao')
        self.hal = OaiSource.objects.get(identifier='hal')
        self.arxiv = OaiSource.objects.get(identifier='arxiv')
        self.lncs = Journal.objects.get(issn='0302-9743')
        self.acm = Journal.objects.get(issn='1529-3785').publisher

    @classmethod
    def tearDownClass(self):
        haystack.connections['default'].get_backend().clear()
        super(PrefilledTest, self).tearDownClass()


def check_paper(asserter, paper):
    """
    All sorts of tests to ensure a paper is well-behaved
    """
    asserter.assertIsInstance(paper, BarePaper)
    # All authors should have valid names
    paper.check_authors()
    # Visible papers should have at least one source
    asserter.assertEqual(paper.visible, not paper.is_orphan())

# Generic test series for a PaperSource instance


class PaperSourceTest(PrefilledTest):

    @classmethod
    def setUpClass(self):
        if self is PaperSourceTest:
            raise unittest.SkipTest("Base test")
        super(PaperSourceTest, self).setUpClass()
        self.source = None
        self.researcher = self.r4

    def test_fetch(self):
        papers = list(self.source.fetch_bare(self.researcher))
        for paper in papers:
            check_paper(self, paper)
            paper = Paper.from_bare(paper)
        self.assertTrue(len(papers) > 1)
        self.check_papers(papers)

    def check_papers(self, papers):
        """
        Method that subclasses can reimplement to check the papers
        downloaded in test_fetch.
        """

    def test_empty(self):
        emptyres = Researcher.create_by_name('Anrscuienrsc', 'Lecsrcudresies')
        papers = list(self.source.fetch_papers(emptyres))
        self.assertEqual(papers, [])


class OrcidUnitTest(unittest.TestCase):

    def test_affiliate_author(self):
        self.assertEqual(
                affiliate_author_with_orcid(
                    ('Jordi', 'Cortadella'),
                    '0000-0001-8114-250X',
                    [('N.', 'Nikitin'), ('J.', 'De San Pedro'), ('J.', 'Carmona'), ('J.', 'Cortadella')]),
                [None, None, None, '0000-0001-8114-250X'])
        self.assertEqual(
                affiliate_author_with_orcid(
                    ('Antonin', 'Delpeuch'),
                    '0000-0002-8612-8827',
                    [('Antonin', 'Delpeuch'), ('Anne', 'Preller')]),
                ['0000-0002-8612-8827', None])


class OrcidIntegrationTest(PaperSourceTest):

    @classmethod
    def setUpClass(self):
        super(OrcidIntegrationTest, self).setUpClass()
        self.source = OrcidPaperSource()

    def check_papers(self, papers):
        p = Paper.objects.get(
            title='From Natural Language to RDF Graphs with Pregroups')
        p.check_authors()
        author = p.authors[0]
        self.assertEqual(author.orcid, self.r4.orcid)
        p = Paper.objects.get(
            title='Complexity of Grammar Induction for Quantum Types')
        p.check_authors()
        author = p.authors[0]
        self.assertEqual(author.orcid, self.r4.orcid)

    def test_previously_present_papers_are_attributed(self):
        # Fetch papers from a researcher
        pablo = Researcher.get_or_create_by_orcid('0000-0002-6293-3231')
        self.source.fetch_and_save(pablo)

        p = Paper.objects.get(oairecord__doi='10.1007/978-3-642-25516-8_1')
        self.assertEqual(p.authors[2].orcid, pablo.orcid)

        # Now fetch a coauthor of him
        antoine = Researcher.get_or_create_by_orcid('0000-0002-7977-4441')
        self.source.fetch_and_save(antoine)

        # This paper should be attributed to both ORCID ids
        p = Paper.objects.get(oairecord__doi='10.1007/978-3-642-25516-8_1')

        self.assertEqual(p.authors[0].orcid, antoine.orcid)
        self.assertEqual(p.authors[2].orcid, pablo.orcid)

    def test_orcid_affiliation(self):
        # this used to raise an error.
        # a more focused test might be preferable (focused on the said
        # paper)
        papers = list(self.source.fetch_orcid_records('0000-0002-9658-1473'))
        self.assertTrue(len(papers) > 30)

    def test_bibtex_fallback(self):
        papers = list(self.source.fetch_orcid_records('0000-0002-1900-3901'))
        titles = [paper.title for paper in papers]
        for p in papers:
            print p.title
            for a in p.authors:
                print a.name.__repr__().encode('utf-8')
                print a.orcid
        self.assertTrue('Company-Coq: Taking Proof General one step closer to a real IDE' in titles)

class PaperMethodsTest(PrefilledTest):

    def test_update_authors(self):
        for old_author_names, new_author_names, final in [
                ([('G.', 'Bodenhausen')],
                 [('Geoffrey', 'Bodenhausen')],
                 [('Geoffrey', 'Bodenhausen')]),
                ([('L. F.', 'Jullien'), ('A.', 'Amarilli')],
                 [('Ludovic', 'Jullien'), ('R.', 'Pérand'), ('Antoine', 'Amarilli')],
                 [('Ludovic F.', 'Jullien'), ('R.', 'Pérand'), ('Antoine', 'Amarilli')]),
                ]:
            paper = Paper.get_or_create('This is a test paper',
                                        [BareName.create_bare(f, l) for (
                                            f, l) in old_author_names],
                                        datetime.date(year=2015, month=04, day=05))
            new_authors = [BareAuthor(name=BareName.create_bare(f, l))
                           for (f, l) in new_author_names]
            paper.update_authors(new_authors)
            self.assertEqual(paper.bare_author_names(), final)

    def test_multiple_get_or_create(self):
        date = datetime.date(year=2003, month=4, day=9)
        paper = Paper.get_or_create('Beta-rays in black pudding',
                                    map(Name.lookup_name, [
                                        ('F.', 'Rodrigo'), ('A.', 'Johnson'), ('Pete', 'Blunsom')]),
                                    date)

        paper2 = Paper.get_or_create('Beta-rays in black pudding',
                                     map(Name.lookup_name, [
                                         ('Frank', 'Rodrigo'), ('A. L.', 'Johnson'), ('P.', 'Blunsom')]),
                                     date)

        self.assertEqual(paper.pk, paper2.pk)
        self.assertEqual(Paper.objects.get(pk=paper.pk).bare_author_names(),
                         [('Frank', 'Rodrigo'), ('A. L.', 'Johnson'), ('Pete', 'Blunsom')])


class TasksTest(PrefilledTest):

    def test_fetch_everything_with_orcid(self):
        r = Researcher.get_or_create_by_orcid('0000-0002-6561-5642')
        fetch_everything_for_researcher(r.pk)


class MaintenanceTest(PrefilledTest):

    @classmethod
    def setUpClass(self):
        super(MaintenanceTest, self).setUpClass()
        self.cr_api = CrossRefAPI()

    def test_cleanup_names(self):
        n = Name.lookup_name(('Anaruic', 'Leclescuantebrste'))
        n.save()
        cleanup_names()
        try:
            n = Name.objects.get(first='Anaruic', last='Leclescuantebrste')
            self.assertTrue(False and 'The name has not been cleaned up')
        except ObjectDoesNotExist:
            pass

    def test_name_initial(self):
        n = self.r2.name
        p = Paper.create_by_doi("10.1002/ange.19941062339")
        n1 = p.authors[0].name
        self.assertEqual((n1.first, n1.last), (n.first, n.last))

    def test_update_paper_statuses(self):
        p = self.cr_api.create_paper_by_doi("10.1016/j.bmc.2005.06.035")
        p = Paper.from_bare(p)
        self.assertEqual(p.pdf_url, None)
        pdf_url = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        OaiRecord.new(source=self.arxiv,
                      identifier='oai:arXiv.org:aunrisste',
                      about=p,
                      splash_url='http://www.perdu.com/',
                      pdf_url=pdf_url)
        update_paper_statuses()
        self.assertEqual(Paper.objects.get(pk=p.pk).pdf_url, pdf_url)
