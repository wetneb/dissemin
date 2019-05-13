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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.
#
import json
import logging
import os
import os.path as path
import shutil
import tarfile
import tempfile

from django.conf import settings

import notification.levels as notification_levels
from notification.api import add_notification_for
from notification.api import delete_notification_per_tag

from backend.crossref import convert_to_name_pair
from backend.crossref import CrossRefAPI
from backend.crossref import fetch_dois
from backend.papersource import PaperSource
from backend.utils import with_speed_report
from papers.baremodels import BareOaiRecord
from papers.baremodels import BarePaper
from papers.errors import MetadataSourceException
from papers.models import OaiSource
from papers.models import Researcher
from papers.orcid import OrcidProfile
from papers.orcid import affiliate_author_with_orcid
from papers.utils import validate_orcid

logger = logging.getLogger('dissemin.' + __name__)


class OrcidPaperSource(PaperSource):
    def __init__(self, *args, **kwargs):
        super(OrcidPaperSource, self).__init__(*args, **kwargs)
        self.oai_source = OaiSource.objects.get(identifier='orcid')

    def fetch_papers(self, researcher, profile=None):
        if not researcher:
            return
        self.researcher = researcher
        if researcher.orcid:
            if researcher.empty_orcid_profile is None:
                self.update_empty_orcid(researcher, True)
            return self.fetch_orcid_records(researcher.orcid, profile=profile)
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
            source=self.oai_source,
            identifier=work.api_uri,
            splash_url=work.splash_url,
            pubtype=work.pubtype
        )

        paper.add_oairecord(record)

        return paper

    def fetch_crossref_incrementally(self, cr_api, orcid_id):
        # If we are using the ORCID sandbox, then do not look for papers from
        # CrossRef as the ORCID ids they contain are production ORCID ids (not
        # fake ones).
        if settings.ORCID_BASE_DOMAIN != 'orcid.org':
            return

        for metadata in cr_api.fetch_all_papers({'orcid': orcid_id}):
            try:
                paper = cr_api.save_doi_metadata(metadata)
                if paper:
                    yield True, paper
                else:
                    yield False, metadata
            except ValueError:
                logger.exception(
                    "Saving CrossRef record from ORCID with id %s failed",
                    orcid_id
                )

    def _oai_id_for_doi(self, orcid_id, doi):
        return 'orcid:{}:{}'.format(orcid_id, doi)

    def fetch_metadata_from_dois(self, cr_api, ref_name, orcid_id, dois):
        doi_metadata = fetch_dois(dois)
        for metadata in doi_metadata:
            try:
                authors = list(map(convert_to_name_pair, metadata['author']))
                orcids = affiliate_author_with_orcid(
                    ref_name, orcid_id, authors)
                paper = cr_api.save_doi_metadata(metadata, orcids)
                if not paper:
                    yield False, metadata
                    continue

                record = BareOaiRecord(
                    source=self.oai_source,
                    identifier=self._oai_id_for_doi(orcid_id, metadata['DOI']),
                    splash_url='https://%s/%s' % (
                        settings.ORCID_BASE_DOMAIN, orcid_id),
                    pubtype=paper.doctype
                )
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
                'papers': ignored_papers,
            }
            add_notification_for(
                [user],
                notification_levels.ERROR,
                notification,
                'backend_orcid'
            )

    def fetch_orcid_records(
            self, orcid_identifier,
            profile=None, use_doi=True, works_dumps_path=None
    ):
        """
        Queries ORCiD to retrieve the publications associated with a given
        ORCiD. It also fetches such papers from the CrossRef search interface.

        :param profile: The ORCID profile if it has already been fetched before
            (format: parsed JSON).
        :param use_doi: Fetch the publications by DOI when we find one
            (recommended, but slow)
        :param works_dumps_path: Path to a dump of XML files for each work of
            the profile. If provided, ``fetch_orcid_records`` uses this dump
            and avoid making API calls to ORCID.
        :returns: a generator, where all the papers found are yielded. (some of
            them could be in free form, hence not imported)
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
        except MetadataSourceException:
            logger.exception("ORCID Profile Error")
            return

        # As we have fetched the profile, let's update the Researcher
        self.researcher = Researcher.get_or_create_by_orcid(
            orcid_identifier,
            profile.json,
            update=True
        )
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
            dois = [doi for doi, _ in dois_and_putcodes]
            metadata = self.fetch_metadata_from_dois(
                cr_api, ref_name, orcid_id, dois
            )
            for idx, (success, paper_or_metadata) in enumerate(metadata):
                if success:
                    yield paper_or_metadata  # We know that this is a paper
                else:
                    put_codes.append(dois_and_putcodes[idx][1])

        # 2nd attempt with ORCID's own crappy metadata
        works = profile.fetch_works(
            put_codes,
            works_dumps_path=works_dumps_path
        )
        for work in works:
            if not work:
                continue

            # If the paper is skipped due to invalid metadata.
            # We first try to reconcile it with local researcher author name.
            # Then, we consider it missed.
            if work.skipped:
                logger.warning(
                    "Work skipped due to incorrect metadata. \n %s",
                    work.skip_reason
                )

                ignored_papers.append(work.as_dict())
                continue

            yield self.create_paper(work)

        self.warn_user_of_ignored_papers(ignored_papers)
        if ignored_papers:
            logger.warning("Total ignored papers: %d", len(ignored_papers))

    def fetch_and_save(self, researcher, profile=None):
        """
        Fetch papers and save them to the database.

        :param incremental: When set to true, papers are clustered
            and commited one after the other. This is useful when
            papers are fetched on the fly for an user.
        """
        count = 0
        for p in self.fetch_papers(researcher, profile=profile):
            try:
                self.save_paper(p, researcher)
            except ValueError:
                continue
            if self.max_results is not None and count >= self.max_results:
                break

            count += 1

    def bulk_import(
            self, summaries_directory, activities_dump, fetch_papers=True,
            use_doi=False, start_from=None
    ):
        """
        Bulk-imports ORCID profiles from a dmup
        (warning: this still uses our DOI cache).
        The directory should contain json versions
        of orcid profiles, as in the official ORCID
        dump.

        :param summaries_directory: The directory to load the JSON ORCID API
            dump (summaries) from.
        :param activities_dump: The tar.gz dump of the ORCID activities (XML
            format).
        :param fetch_papers: Whether to only import the ORCID profiles or the
            complete ORCID profiles with their records (default).
        :param use_doi: Whether to rely only on ORCID's metadata (default) or
            to also query Crossref API for all found DOIs.
        :param start_from: An optional folder name to start from (directory
            under the summaries folder).

        .. note :: ORCID activities dump is very large and difficult to work
        with. The trick here is to extract activities from the ORCID dump by
        toplevel folder and then process the whole folder and move to the next
        one. Folders have to be treated in the order of appearance in the
        tarball to be more efficient.
        """
        seen = False
        archive = tarfile.open(activities_dump, 'r:gz')

        members_to_extract = []
        member = archive.next()
        while member is not None:
            # Skip root directory from the tarball
            if member.name == 'activities':
                member = archive.next()
                continue

            # New folder
            if member.name.count('/') == 1:
                if members_to_extract:
                    # Import folder
                    orcid_toplevel_folder = (
                        members_to_extract[0].name.split('/')[-1]
                    )
                    summaries_path = path.join(
                        summaries_directory, orcid_toplevel_folder
                    )
                    # Eventually skip first entries
                    if orcid_toplevel_folder == start_from:
                        seen = True
                    if start_from and not seen:
                        continue

                    # Only extract works, we don't care about education etc
                    members_to_extract = [
                        archive_member
                        for archive_member in members_to_extract
                        if '/works/' in archive_member.name
                    ]

                    # Extract current toplevel folder to a tmp directory
                    temp_dir = tempfile.mkdtemp(prefix='dissemin-orcid-')
                    logger.info(
                        'Extracting folder %s from activities archive.',
                        orcid_toplevel_folder
                    )
                    archive.extractall(
                        path=temp_dir,
                        members=members_to_extract
                    )

                    # Import the ORCID profiles for this toplevel directory
                    # from the summaries dump
                    summaries_files_with_speed = with_speed_report(
                        os.listdir(summaries_path),
                        name='ORCID profiles'
                    )
                    for summary_file in summaries_files_with_speed:
                        fpath = path.join(summaries_path, summary_file)
                        with open(fpath, 'r') as fh:
                            try:
                                profile = json.load(fh)
                                orcid = profile['orcid-identifier']['path']
                                r = Researcher.get_or_create_by_orcid(
                                    orcid,
                                    profile,
                                    update=True
                                )
                                if fetch_papers:
                                    papers = self.fetch_orcid_records(
                                        orcid,
                                        profile=OrcidProfile(json=profile),
                                        use_doi=use_doi,
                                        works_dumps_path=path.join(
                                            temp_dir,
                                            'activities',
                                            orcid_toplevel_folder,
                                            summary_file.replace('.json', ''),
                                            'works'
                                        )
                                    )
                                    for p in papers:
                                        self.save_paper(p, r)
                            except (ValueError, KeyError):
                                logger.warning(
                                    "Invalid profile: %s",
                                    fpath
                                )
                            # Do not interrupt the import because a profile
                            # could not be imported
                            except Exception as exc:
                                logger.warning(
                                    "An error occurred while importing %s: %s",
                                    fpath,
                                    exc
                                )
                                raise
                    # Remove temporary directory
                    shutil.rmtree(temp_dir)
                # Reset members list
                members_to_extract = []
            # Any member
            members_to_extract.append(member)
            member = archive.next()
        archive.close()
