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
from papers.errors import MetadataSourceException
from papers.models import OaiSource
from papers.models import Researcher
from papers.orcid import OrcidProfile
from papers.orcid import affiliate_author_with_orcid
from papers.utils import validate_orcid

### Metadata manipulation utilities ####

def orcid_oai_source():
    return OaiSource.objects.get(identifier='orcid')


### Paper fetching ####

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

    def create_paper(self, work):
        assert (not work.skipped)
        # Create paper
        authors, orcids = work.authors_and_orcids
        paper = BarePaper.create(
            work.title,
            authors,
            work.pubdate,
            visible=True,
            affiliations=None,
            orcids=orcids,
        )
        record = BareOaiRecord(
            source=orcid_oai_source(),
            identifier=work.api_uri,
            splash_url=work.splash_url,
            pubtype=work.pubtype
        )

        paper.add_oairecord(record)

        return paper

    def fetch_crossref_incrementally(self, cr_api, orcid_id):
        # If we are using the ORCID sandbox, then do not look for papers from CrossRef
        # as the ORCID ids they contain are production ORCID ids (not fake
        # ones).
        if settings.ORCID_BASE_DOMAIN != 'orcid.org':
            return

        for metadata in cr_api.fetch_all_papers({'orcid': orcid_id}):
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
                        splash_url='https://%s/%s' % (
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
        ignored_papers = []  # list of ignored papers due to incomplete metadata

        # Get summary publications and separate them in two classes:
        # - the ones with DOIs, that we will fetch with CrossRef
        dois_and_putcodes = []  # list of (DOIs,putcode) to fetch
        # - the ones without: we will fetch ORCID's metadata about them
        #   and try to create a paper with what they provide
        put_codes = []
        for summary in profile.work_summaries:
            if summary.doi and use_doi:
                dois_and_putcodes.append((summary.doi, summary.put_code))
            else:
                put_codes.append(summary.put_code)

        # 1st attempt with DOIs and CrossRef
        if use_doi:
            # Let's grab papers with DOIs found in our ORCiD profile.
            dois = [doi for doi, put_code in dois_and_putcodes]
            for idx, (success, paper_or_metadata) in enumerate(self.fetch_metadata_from_dois(cr_api, ref_name, orcid_id, dois)):
                if success:
                    yield paper_or_metadata
                else:
                    put_codes.append(dois_and_putcodes[idx][1])

        # 2nd attempt with ORCID's own crappy metadata
        works = profile.fetch_works(put_codes)
        for work in works:
            if not work:
                continue

            # If the paper is skipped due to invalid metadata.
            # We first try to reconcile it with local researcher author name.
            # Then, we consider it missed.
            if work.skipped:
                print('%s is skipped due to incorrect metadata (%s)' %
                    (work, work.skip_reason))

                ignored_papers.append(work.as_dict())
                continue

            yield self.create_paper(work)

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

