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



import codecs
import os
import pytest
import unittest

from mock import patch
from oaipmh.error import CannotDisseminateFormatError
from oaipmh.error import IdDoesNotExistError
from oaipmh.client import Client

from django.test import TestCase

from backend.oai import OaiPaperSource
from papers.models import OaiRecord
from papers.models import OaiSource
from papers.models import Paper


class OaiTest(TestCase):

    def setUp(self):
        oaisource = OaiSource.objects.get(identifier='hal')
        self.oai = OaiPaperSource(oaisource)
        self.testdir = os.path.dirname(os.path.abspath(__file__))
        base_oaisource = OaiSource.objects.get(identifier='base')
        base_oaisource.endpoint = 'https://some_endpoint'
        self.base_oai = OaiPaperSource(base_oaisource)

    def create(self, *args, **kwargs):
        # Shortcut for the tests
        if args[1] == 'oai_dc':
            return self.oai.create_paper_by_identifier(*args, **kwargs)
        else:
            identifier = args[0]
            fname = identifier.replace('/', '_') + '.xml'
            with codecs.open(os.path.join(self.testdir, 'data', fname), 'r', 'utf-8') as f:
                oai_record = f.read()
            with patch.object(Client, 'makeRequest', return_value=oai_record.encode('utf-8')):
                return self.base_oai.create_paper_by_identifier(*args, **kwargs)

    def delete(self, identifier):
        try:
            r = OaiRecord.objects.get(identifier=identifier)
            p = r.about
            r.delete()
            if p.is_orphan():
                p.delete()
        except OaiRecord.DoesNotExist:
            pass
        
    def test_read_dump(self):
        """
        Reads a small example dump from BASE
        """
        records = self.base_oai.read_base_dump(os.path.join(self.testdir, 'data/example_base_dump'), 'base_dc')
        # Fetch the records
        records = list(records)
        titles = [record.getField('title') for _, record, _ in records]
        self.assertEqual(len(records), 20)
        self.assertTrue(['Modularizing the Elimination of r=0 in Kleene Algebra'] in titles)
        
    def test_load_dump(self):
        """
        Loads up a dump in the DB.
        """
        self.base_oai.load_base_dump(os.path.join(self.testdir, 'data/example_base_dump'))
        # Loading it a second time should be very quick
        self.base_oai.load_base_dump(os.path.join(self.testdir, 'data/example_base_dump'))
        
        paper = Paper.objects.get(title='Modularizing the Elimination of r=0 in Kleene Algebra')
        self.assertEqual(paper.pdf_url, 'http://dx.doi.org/10.2168/lmcs-1(3:5)2005')
        

    def test_create_no_match(self):
        """
        Creation of a paper from an OAI record,
        when the paper does not exist yet.
        """
        oai_id = 'oai:HAL:hal-01063697v1'

        # first, make sure the paper isn't there already
        self.delete(oai_id)
        # create a paper from BASE
        hal_paper = self.create(oai_id, 'oai_dc')
        self.assertEqual(len(hal_paper.oairecords), 1)
        self.assertNotEqual(hal_paper.pdf_url, None)
        self.assertEqual(hal_paper.fingerprint,
                         hal_paper.new_fingerprint())

    def test_create_already_existing(self):
        """
        Creation of a paper from an OAI record,
        when the exact same OAI record already exists.
        """
        # TODO we could repeat this for various papers
        oai_id = 'oai:hal.archives-ouvertes.fr:hal-00830421'

        # first, make sure the paper isn't there already
        self.delete(oai_id)
        # create a paper from BASE
        hal_paper = self.create(oai_id, 'oai_dc')

        # Create it again!
        new_paper = self.create(oai_id, 'oai_dc')

        # It's the same thing!
        self.assertEqual(new_paper, hal_paper)
        self.assertSetEqual(set(new_paper.oairecords),
                            set(hal_paper.oairecords))
        self.assertListEqual(new_paper.bare_author_names(),
                             hal_paper.bare_author_names())
        self.assertEqual(new_paper.title, hal_paper.title)

    @pytest.mark.usefixtures('mock_doi')
    def test_create_match_fp(self):
        """
        Addition of an OAI record when it is matched
        with an existing record by fingerprint.
        """
        doi = '10.1016/j.crma.2012.10.021'
        oai_id = 'ftarxivpreprints:oai:arXiv.org:1112.6130'

        # first, make sure the paper isn't there already
        Paper.objects.filter(oairecord__doi=doi).delete()
        # create a paper from BASE
        cr_paper = Paper.create_by_doi(doi)

        # Save the existing records
        records = set(cr_paper.oairecords)
        # Create a new paper (refers to the same paper, but coming from
        # another source)
        new_paper = self.create(oai_id, 'base_dc')
        # the resulting paper has to be equal to the first one
        # (this does not check that all their attributes are equal, just
        # that they are the same row in the database, i.e. have same id)
        self.assertEqual(new_paper, cr_paper)
        # the new set of records is the old one plus the new record
        records.add(OaiRecord.objects.get(identifier=oai_id))
        self.assertSetEqual(set(new_paper.oairecords), records)

    @unittest.expectedFailure
    def test_create_incomplete_metadata(self):
        """
        When we are trying to create a new paper for an
        incomplete OAI record (in this case, a publication date is
        missing). Ideally we would still like to match it with the
        first paper via fingerprint, to add the relevant url.
        """
        first_id = 'ftccsdartic:oai:hal.archives-ouvertes.fr:hal-00939473'
        second_id = 'ftciteseerx:oai:CiteSeerX.psu:10.1.1.487.869'

        # first, make sure the paper isn't there already
        self.delete(first_id)
        # create a paper from BASE
        cr_paper = self.create(first_id, 'base_dc')

        # Save the existing records
        records = set(cr_paper.oairecords)
        # Create a new paper (refers to the same paper, but coming from
        # another source)
        new_paper = self.create(second_id, 'base_dc')
        # the resulting paper has to be equal to the first one
        # (this does not check that all their attributes are equal, just
        # that they are the same row in the database, i.e. have same id)
        self.assertEqual(new_paper, cr_paper)
        # the new set of records is the old one plus the new record
        records.add(OaiRecord.objects.get(identifier=second_id))
        self.assertSetEqual(set(new_paper.oairecords), records)


    @pytest.mark.usefixtures('mock_doi')
    def test_create_match_doi(self):
        """
        Addition of an OAI record when it is matched
        to an existing paper by DOI
        """
        first_id = 'ftunivmacedonia:oai:dspace.lib.uom.gr:2159/6240'
        doi = '10.1111/j.1574-0862.2005.00325.x'

        # first, make sure the paper isn't there already
        self.delete(first_id)
        # Create a paper from BASE
        first = Paper.create_by_doi(doi)

        self.assertEqual(first.oairecords[0].doi, doi)
        records = set(first.oairecords)
        new_paper = self.create(first_id, 'base_dc')

        # Make sure that, if a merge happens, the oldest
        # paper remains (otherwise we create broken links!)
        self.assertEqual(first, new_paper)

        records.add(OaiRecord.objects.get(identifier=first_id))
        self.assertEqual(set(new_paper.oairecords), records)

    @pytest.mark.usefixtures('mock_doi')
    def test_update_pdf_url(self):
        """
        Two OAI records share the same splash URL, but
        the second one has a pdf_url. We should add the PDF
        url to the existing OAI record (merge the two records).
        """
        # first, make sure the paper isn't there already
        self.delete('oai:crossref.org:10.1007/s10858-015-9994-8')
        # Create a paper from Crossref
        first = Paper.create_by_doi('10.1007/s10858-015-9994-8')
        # initially the PDF url should be empty
        assert not first.oairecords[0].pdf_url

        # then we import a new identifier
        new_paper = self.create(
            'ftspringeroc:10.1007/s10858-015-9994-8',
            'base_dc')
        self.assertEqual(first, new_paper)

        # no new record should be created
        self.assertEqual(len(new_paper.oairecords), 1)
        self.assertNotEqual(new_paper.oairecords[0].pdf_url, None)

    def test_create_match_identifier(self):
        """
        An OAI record with the same identifier already
        exists but it has been already merged before with
        another paper with a different fingerprint.
        """
        identifier = 'ftccsdartic:oai:hal.archives-ouvertes.fr:hal-00939473'

        # create a paper from BASE
        hal_paper = self.create(identifier, 'base_dc')
        records = set(hal_paper.oairecords)
        # change its fingerprint
        hal_paper.title += ' babebibobu'
        hal_paper.fingerprint = hal_paper.new_fingerprint()
        hal_paper.save()

        # add the OAI record again
        new_paper = self.create(identifier, 'base_dc')
        self.assertEqual(new_paper, hal_paper)
        self.assertSetEqual(records, set(new_paper.oairecords))

    def test_create_invalid_metadata(self):
        """
        Metadata that we don't accept
        """
        identifiers = [
            # Contributors too long to fit in the db
            ('ftbnfgallica:oai:bnf.fr:gallica/ark:/12148/btv1b8621766k',
             'base_dc'),
            # No authors
            ('ftcarmelhelios:oai:archive.library.cmu.edu:heinz:box00200/fld00021/bdl0031/doc0001/',
             'base_dc'),
            # Bad publication date
            ('ftsehiruniv:oai:earsiv.sehir.edu.tr:11498/28266',
             'base_dc'),
         ]
        for i, f in identifiers:
            self.assertEqual(
                self.create(i, f),
                None)

    def test_create_invalid_identifier(self):
        """
        Fetching an invalid identifier from OAI
        """
        with self.assertRaises(IdDoesNotExistError):
            self.create('aiunrsecauiebleuiest', 'oai_dc')

    def test_create_invalid_format(self):
        """
        Fetching with an invalid format from OAI
        """
        # Format not available from the interface
        with self.assertRaises(CannotDisseminateFormatError):
            self.create('oai:arXiv.org:0704.0001', 'unknown_format')

    # tests of particular translators
    # TODO: translate them as tests of the translators and not the
    # whole backend?

    def test_base_doctype(self):
        mappings = {
            'ftunivsavoie:oai:HAL:hal-01062241v1': 'proceedings-article',
            'ftunivsavoie:oai:HAL:hal-01062339v1': 'book-chapter',
            'ftunivmacedonia:oai:dspace.lib.uom.gr:2159/6227': 'preprint',
            'ftartxiker:oai:HAL:hal-00845819v1': 'preprint',
            'ftdatacite:oai:oai.datacite.org:402223': 'preprint',
        }

        for ident, typ in list(mappings.items()):
            paper = self.create(ident, 'base_dc')
            self.assertEqual(paper.doctype, typ)

    def test_datacite(self):
        paper = self.create(
                'ftdatacite:oai:oai.datacite.org:8558707',
                'base_dc')
        self.assertTrue(paper.pdf_url)

    def test_pmc(self):
        paper = self.create(
                'ftpubmed:oai:pubmedcentral.nih.gov:1968744',
                'base_dc')
        self.assertEqual(paper.pdf_url, 'http://www.ncbi.nlm.nih.gov/pmc/articles/PMC1968744')
        p2 = self.create(
                'ftpubmed:oai:pubmedcentral.nih.gov:4131942',
                'base_dc')
        self.assertEqual(p2.pdf_url,'http://www.ncbi.nlm.nih.gov/pubmed/24806729')

    def test_doi_prefix(self):
        paper = self.create(
                'ftdatacite:oai:oai.datacite.org:3505359',
                'base_dc')
        self.assertTrue(paper.pdf_url is not None)
