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



import datetime
import unittest

from backend.crossref import CrossRefAPI
from backend.maintenance import update_paper_statuses
from backend.tasks import fetch_everything_for_researcher
from django.test import TestCase
import pytest

from papers.baremodels import BareAuthor
from papers.baremodels import BareName
from papers.baremodels import BarePaper
from papers.models import Name
from papers.models import OaiRecord
from papers.models import Paper
from papers.models import Researcher

from papers.tests.test_orcid import OrcidProfileStub

TEST_INDEX = {
    'default': {
        'ENGINE': 'search.SearchEngine',
        'URL': 'http://localhost:9200/',
        'INDEX_NAME': 'dissemin_test',
    },
}

def get_researcher_by_name(first, last):
    n = Name.lookup_name((first, last))
    return Researcher.objects.get(name=n)


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

@pytest.mark.usefixtures("load_test_data")
class PaperSourceTest(TestCase):

    def setUp(self):
        if type(self) is PaperSourceTest:
            raise unittest.SkipTest("Base test")
        self.source = None
        self.researcher = self.r4

    def test_fetch(self):
        papers = list(self.source.fetch_papers(self.researcher))
        for paper in papers:
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

@pytest.mark.usefixtures("load_test_data")
class PaperMethodsTest(TestCase):

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
                                        datetime.date(year=2015, month=0o4, day=0o5))
            new_authors = [BareAuthor(name=BareName.create_bare(f, l))
                           for (f, l) in new_author_names]
            paper.update_authors(new_authors)
            self.assertEqual(paper.bare_author_names(), final)

    def test_multiple_get_or_create(self):
        date = datetime.date(year=2003, month=4, day=9)
        paper = Paper.get_or_create('Beta-rays in black pudding',
                                    list(map(Name.lookup_name, [
                                        ('F.', 'Rodrigo'), ('A.', 'Johnson'), ('Pete', 'Blunsom')])),
                                    date)

        paper2 = Paper.get_or_create('Beta-rays in black pudding',
                                     list(map(Name.lookup_name, [
                                         ('Frank', 'Rodrigo'), ('A. L.', 'Johnson'), ('P.', 'Blunsom')])),
                                     date)

        self.assertEqual(paper.pk, paper2.pk)
        self.assertEqual(Paper.objects.get(pk=paper.pk).bare_author_names(),
                         [('Frank', 'Rodrigo'), ('A. L.', 'Johnson'), ('Pete', 'Blunsom')])

class TasksTest(TestCase):

    def test_fetch_everything_with_orcid(self):
        profile = OrcidProfileStub('0000-0002-9658-1473', instance='orcid.org')
        r = Researcher.get_or_create_by_orcid('0000-0002-9658-1473', profile=profile)
        fetch_everything_for_researcher(r.pk)

@pytest.mark.usefixtures("load_test_data")
class MaintenanceTest(TestCase):

    @classmethod
    def setUpClass(self):
        super(MaintenanceTest, self).setUpClass()
        self.cr_api = CrossRefAPI()

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
