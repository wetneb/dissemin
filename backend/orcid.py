# -*- encoding: utf-8 -*-

# Dissemin: open access policy enforcement tool
# Copyright (C) 2014 Antonin Delpeuch
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

from __future__ import unicode_literals

#from requests.exceptions import RequestException
#import json, requests
import os
import os.path as path
import json
from backend.crossref import convert_to_name_pair
from backend.crossref import CrossRefAPI
from backend.crossref import fetch_dois
from backend.papersource import PaperSource
from django.conf import settings
from notification.api import add_notification_for
from notification.api import delete_notification_per_tag
import notification.levels as notification_levels
from papers.baremodels import BareOaiRecord
from papers.baremodels import BarePaper
from papers.baremodels import BareName
from papers.bibtex import parse_bibtex
from papers.doi import to_doi
from papers.errors import MetadataSourceException
from papers.models import OaiSource
from papers.models import Researcher
from papers.name import parse_comma_name
from papers.name import most_similar_author
from papers.orcid import OrcidProfile
from papers.utils import jpath
from papers.utils import parse_int
from papers.utils import try_date
from papers.utils import validate_orcid

### Metadata manipulation utilities ####

orcid_type_to_pubtype = {
        'book': 'book',
        'book-chapter': 'book-chapter',
        'book-review': 'other',
        'dictionary-entry': 'reference-entry',
        'dissertation': 'thesis',
        'encyclopedia-entry': 'reference-entry',
        'edited-book': 'book',
        'journal-article': 'journal-article',
        'journal-issue': 'journal-issue',
        'magazine-article': 'other',
        'manual': 'other',
        'online-resource': 'dataset',
        'newsletter-article': 'other',
        'newspaper-article': 'other',
        'report': 'report',
        'research-tool': 'other',
        'supervised-student-publication': 'other',
        'test': 'other',
        'translation': 'other',
        'website': 'other',
        'working-paper': 'preprint',
        'conference-abstract': 'other',
        'conference-paper': 'proceedings-article',
        'conference-poster': 'poster',
        # Intellectual property section: skipped (-> 'other')
        'data-set': 'dataset',
    }


def orcid_oai_source():
    return OaiSource.objects.get(identifier='orcid')


def orcid_to_doctype(typ):
    return orcid_type_to_pubtype.get(typ.lower().replace('_', '-').replace(' ', '-'), 'other')


def affiliate_author_with_orcid(ref_name, orcid, authors, initial_orcids=None):
    """
    Given a reference name and an ORCiD for a researcher, find out which
    author in the list is the most likely to be that author. This function
    is run on author lists of papers listed in the ORCiD record so we expect
    that one of the authors should be the same person as the ORCiD holder.
    This just finds the most similar name and returns the appropriate orcids
    list (None everywhere except for the most similar name where it is the ORCiD).
    """
    max_sim_idx = most_similar_author(ref_name, authors)
    orcids = [None]*len(authors)
    if initial_orcids and len(initial_orcids) == len(authors):
        orcids = initial_orcids
    if max_sim_idx is not None:
        orcids[max_sim_idx] = orcid
    return orcids

### Paper fetching ####


class SkippedPaper(Exception):
    pass


class ORCIDMetadataExtractor(object):

    def __init__(self, pub):
        self._pub = pub

    def dois(self):
        dois = []
        for extid in self.j('work-external-identifiers/work-external-identifier', []):
            if extid.get('work-external-identifier-type') == 'DOI':
                doi = to_doi(jpath('work-external-identifier-id/value', extid))
                if doi:
                    # If a DOI is available, create the paper using metadata from CrossRef.
                    # We don't do it yet, we only store the DOI, so that we can fetch them
                    # by batch later.
                    dois.append(doi)
        return dois

    def title(self):
            # Title
        title = self.j('work-title/title/value')
        if title is None:
            print("Warning: Skipping ORCID publication: no title")
            raise SkippedPaper("NO_TITLE")
        else:
            return title

    def type(self):
        return orcid_to_doctype(self.j('work-type', 'other'))

    def contributors(self):
        # Contributors (ignored for now as they are very often not present)
        def get_contrib(js):
            return {
                    'orcid': jpath('contributor-orcid', js),
                    'name': jpath('credit-name/value', js),
            }

        return map(get_contrib, self.j('work-contributors/contributor', []))

    def authors_from_contributors(self, contributors):
        author_names = [c['name'] for c in contributors if c['name'] is not None]
        return map(parse_comma_name, author_names)

    def pubdate(self):
            # Pubdate
            # Remark(RaitoBezarius): we don't want to put 01 ; it could be
            # interpreted as octal 1.
        year = parse_int(self.j('publication-date/year/value'), 1970)
        month = parse_int(self.j('publication-date/month/value'), 1)
        day = parse_int(self.j('publication-date/day/value'), 1)
        pubdate = try_date(year, month, day) or try_date(
            year, month, 1) or try_date(year, 1, 1)
        if pubdate is None:
            print("Invalid publication date in ORCID publication, skipping")
            raise SkippedPaper("INVALID_PUB_DATE")
        else:
            return pubdate

    def internal_identifier(self):
        # ORCiD internal id
        return self.j('put-code')

    def orcids(self, orcid_id, ref_name, authors, initial_orcids):
        return affiliate_author_with_orcid(ref_name, orcid_id, authors, initial_orcids=initial_orcids)

    def citation_format(self):
        return self.j('work-citation/work-citation-type')

    def bibtex(self):
        return self.j('work-citation/citation')

    def authors_from_bibtex(self, bibtex):
        if bibtex is not None:
            try:
                entry = parse_bibtex(bibtex)

                if 'author' not in entry or len(entry['author']) == 0:
                    print("Warning: ORCiD publication with no authors.")
                    print(bibtex)
                    return []
                else:
                    return entry['author']
            except ValueError:
                return []
        else:
            return []

    def convert_authors(self, authors, orcids):
        names = [BareName.create_bare(first, last)
                for first, last in authors]
        names_and_orcids = zip(names, orcids)
        filtered = [(n,o) for n, o in names_and_orcids if  n is not None ]
        final_names = [n for n, o in filtered]
        final_orcids = [o for n, o in filtered]
        return final_names, final_orcids

    def j(self, path, default=None):
        return jpath(path, self._pub, default)


class ORCIDDataPaper(object):

    def __init__(self, orcid_id):
        self.id = orcid_id

        self.title = None
        self.pubdate = None
        self.doctype = None
        self.identifier = None
        self.citation_format = None
        self.bibtex = None

        self.authors = []
        self.contributors = []
        self.orcids = []

        self.dois = []

        self.skipped = False
        self.skip_reason = None

    def initialize(self):
        try:
            self.throw_skipped()
        except SkippedPaper as e:
            self.skipped = True
            self.skip_reason, = e.args

    def is_skipped(self):
        return any(lambda item: not item,
                   [
                    self.title,
                    self.authors,
                    self.pubdate
                       ])

    def throw_skipped(self):
        if not self.title:
            raise SkippedPaper('NO_TITLE')

        if not self.authors:
            raise SkippedPaper('NO_AUTHOR')

        if not self.pubdate:
            raise SkippedPaper('NO_PUBDATE')

    @classmethod
    def from_orcid_metadata(cls, ref_name, orcid_id, pub, stop_if_dois_exists=False, overrides=None):
        if overrides is None:
            overrides = {}

        extractor = ORCIDMetadataExtractor(pub)
        paper = ORCIDDataPaper(orcid_id)

        for key, value in overrides.items():
            setattr(paper, key, value)

        try:
            paper.dois.extend(extractor.dois())  # We concat lists.
            if paper.dois and stop_if_dois_exists:
                return paper

            paper.title = extractor.title()
            paper.doctype = extractor.type()
            # paper.contributors = extractor.contributors()
            # paper.authors.extend(extractor.authors_from_contributors(paper.contributors))
            paper.pubdate = extractor.pubdate()
            paper.identifier = extractor.internal_identifier()

            paper.citation_format = extractor.citation_format()
            paper.bibtex = extractor.bibtex()
            paper.authors.extend(extractor.authors_from_bibtex(paper.bibtex))

            paper.orcids = extractor.orcids(
                orcid_id, ref_name, paper.authors, paper.orcids)
            paper.authors, paper.orcidse = extractor.convert_authors(paper.authors, paper.orcids)

            paper.initialize()
            return paper
        except SkippedPaper as e:
            paper.skipped = True
            paper.skip_reason, = e.args

    def __repr__(self):
        return '<ORCIDDataPaper %s written by %s>' % (self.title, ', '.join(self.authors))

    def __str__(self):
        return self.title

    @property
    def splash_url(self):
        return 'http://{}/{}'.format(settings.ORCID_BASE_DOMAIN, self.id)

    def as_dict(self):
        return self.__dict__


class OrcidPaperSource(PaperSource):

    def fetch_papers(self, researcher):
        if not researcher:
            return
        self.researcher = researcher
        if researcher.orcid:
            if researcher.empty_orcid_profile == None:
                self.update_empty_orcid(researcher, True)
            return self.fetch_orcid_records(researcher.orcid)
        return []

    def reconcile_paper(self, ref_name, orcid_id, metadata, overrides=None):
        if overrides is None:
            overrides = {}

        return ORCIDDataPaper.from_orcid_metadata(
            ref_name,
            orcid_id,
            metadata,
            overrides=overrides
        )

    def create_paper(self, data_paper):
        assert (not data_paper.skipped)
        # Create paper
        paper = BarePaper.create(
            data_paper.title,
            data_paper.authors,
            data_paper.pubdate,
            visible=True,
            affiliations=None,
            orcids=data_paper.orcids,
        )
        record = BareOaiRecord(
            source=orcid_oai_source(),
            identifier=data_paper.identifier,
            splash_url=data_paper.splash_url,
            pubtype=data_paper.doctype
        )

        paper.add_oairecord(record)

        return paper

    def fetch_crossref_incrementally(self, cr_api, orcid_id):
        # If we are using the ORCID sandbox, then do not look for papers from CrossRef
        # as the ORCID ids they contain are production ORCID ids (not fake
        # ones).
        if settings.ORCID_BASE_DOMAIN != 'orcid.org':
            return

        for metadata in cr_api.search_for_dois_incrementally('', {'orcid': orcid_id}):
            try:
                paper = cr_api.save_doi_metadata(metadata)
                if paper:
                    yield True, paper
                else:
                    yield False, metadata
            except ValueError as e:
                print "Saving CrossRef record from ORCID failed: %s" % unicode(e)

    def fetch_metadata_from_dois(self, cr_api, ref_name, orcid_id, dois):
        doi_metadata = fetch_dois(dois)
        for metadata in doi_metadata:
            try:
                authors = map(convert_to_name_pair, metadata['author'])
                orcids = affiliate_author_with_orcid(
                    ref_name, orcid_id, authors)
                paper = cr_api.save_doi_metadata(metadata, orcids)
                if not paper:
                    yield False, metadata
                    continue

                record = BareOaiRecord(
                        source=orcid_oai_source(),
                        identifier='orcid:%s:%s' % (orcid_id, metadata['DOI']),
                        splash_url='http://%s/%s' % (
                            settings.ORCID_BASE_DOMAIN, orcid_id),
                        pubtype=paper.doctype)
                paper.add_oairecord(record)
                yield True, paper
            except (KeyError, ValueError, TypeError):
                yield False, metadata

    def warn_user_of_ignored_papers(self, ignored_papers):
        if self.researcher is None:
            return
        user = self.researcher.user
        if user is None:
            return
        delete_notification_per_tag(user, 'backend_orcid')
        if ignored_papers:
            notification = {
                'code': 'IGNORED_PAPERS',
                'papers': ignored_papers
            }
            add_notification_for([user],
                                    notification_levels.ERROR,
                                    notification,
                                    'backend_orcid'
                                    )

    def fetch_orcid_records(self, orcid_identifier, profile=None, use_doi=True):
        """
        Queries ORCiD to retrieve the publications associated with a given ORCiD.
        It also fetches such papers from the CrossRef search interface.

        :param profile: The ORCID profile if it has already been fetched before (format: parsed JSON).
        :param use_doi: Fetch the publications by DOI when we find one (recommended, but slow)
        :returns: a generator, where all the papers found are yielded. (some of them could be in
                free form, hence not imported)
        """
        cr_api = CrossRefAPI()

        # Cleanup iD:
        orcid_id = validate_orcid(orcid_identifier)
        if orcid_id is None:
            raise MetadataSourceException('Invalid ORCiD identifier')

        # Get ORCiD profile
        try:
            if profile is None:
                profile = OrcidProfile(orcid_id=orcid_id)
            else:
                profile = OrcidProfile(json=profile)
        except MetadataSourceException as e:
            print e
            return

        # As we have fetched the profile, let's update the Researcher
        self.researcher = Researcher.get_or_create_by_orcid(orcid_identifier,
                profile.json, update=True)
        if not self.researcher:
            return

        # Reference name
        ref_name = profile.name
        # curl -H "Accept: application/orcid+json"
        # 'http://pub.orcid.org/v1.2/0000-0002-8612-8827/orcid-works' -L -i
        dois = []  # list of DOIs to fetch
        ignored_papers = []  # list of ignored papers due to incomplete metadata

        # Fetch publications (1st attempt with ORCiD data)
        pubs = jpath(
            'orcid-profile/orcid-activities/orcid-works/orcid-work', profile, [])
        for pub in pubs:
            data_paper = ORCIDDataPaper.from_orcid_metadata(
                ref_name,
                orcid_id,
                pub,
                stop_if_dois_exists=use_doi
            )
            if not data_paper:
                continue

            if data_paper.dois and use_doi:  # We want to batch it rather than manually do it.
                dois.extend(data_paper.dois)
                continue

            # If the paper is skipped due to invalid metadata.
            # We first try to reconcile it with local researcher author name.
            # Then, we consider it missed.
            if data_paper.skipped:
                data_paper = self.reconcile_paper(
                    ref_name,
                    orcid_id,
                    pub,
                    overrides={
                        'authors': [(self.researcher.name.first, self.researcher.name.last)]
                    }
                )
                if data_paper.skipped:
                    print('%s is skipped due to incorrect metadata (%s)' %
                        (data_paper, data_paper.skip_reason))

                    ignored_papers.append(data_paper.as_dict())
                    continue

            yield self.create_paper(data_paper)

        # 2nd attempt with DOIs and CrossRef
        if use_doi:
            # Let's grab papers from CrossRef
            #for success, paper_or_metadata in self.fetch_crossref_incrementally(cr_api, orcid_id):
            #    if success:
            #        yield paper_or_metadata
            #    else:
            #        ignored_papers.append(paper_or_metadata)
            #        print('This metadata (%s) yields no paper.' %
            #              (unicode(paper_or_metadata)))

            # Let's grab papers with DOIs found in our ORCiD profile.
            # FIXME(RaitoBezarius): if we fail here, we should get back the pub
            # and yield it.
            for success, paper_or_metadata in self.fetch_metadata_from_dois(cr_api, ref_name, orcid_id, dois):
                if success:
                    yield paper_or_metadata
                else:
                    ignored_papers.append(paper_or_metadata)
                    print('This metadata (%s) yields no paper.' %
                          (paper_or_metadata))

        self.warn_user_of_ignored_papers(ignored_papers)
        if ignored_papers:
            print('Warning: Total ignored papers: %d' % (len(ignored_papers)))


    def bulk_import(self, directory, fetch_papers=True, use_doi=False):
        """
        Bulk-imports ORCID profiles from a dmup
        (warning: this still uses our DOI cache).
        The directory should contain json versions
        of orcid profiles, as in the official ORCID
        dump.
        """

        for root, _, fnames in os.walk(directory):
            for fname in fnames:
                #if fname == '0000-0003-1349-4524.json':
                #    seen = True
                #if not seen:
                #    continue

                with open(path.join(root, fname), 'r') as f:
                    try:
                        profile = json.load(f)
                        orcid = profile['orcid-profile'][
                                        'orcid-identifier'][
                                        'path']
                        r = Researcher.get_or_create_by_orcid(
                            orcid, profile, update=True)
                        if fetch_papers:
                            papers = self.fetch_orcid_records(orcid,
                                profile=profile,
                                use_doi=use_doi)
                            for p in papers:
                                self.save_paper(p, r)
                    except (ValueError, KeyError):
                        print "Invalid profile: %s" % fname

