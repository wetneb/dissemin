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



from backend.extractors import REGISTERED_OAI_EXTRACTORS
from backend.extractors import defaultExtractor
from papers.baremodels import BareName
from papers.baremodels import BareOaiRecord
from papers.baremodels import BarePaper
from papers.doi import to_doi
from papers.name import parse_comma_name
from papers.utils import sanitize_html
from papers.utils import tolerant_datestamp_to_datetime
from papers.utils import valid_publication_date
from oaipmh.error import DatestampError
from backend.pubtype_translations import OAI_PUBTYPE_TRANSLATIONS
import logging

logger = logging.getLogger('dissemin.' + __name__)

class OaiTranslator(object):
    """
    A translator takes a metadata record from the OAI-PMH
    proxy and converts it to a :class:`BarePaper`.
    """

    def __init__(self, oaisource):
        """
        Inits the translator to create OaiRecords linked to the
        given OaiSource
        """
        self.oaisource = oaisource

    def format(self):
        """
        Returns the metadata format expected by the translator
        """
        raise NotImplementedError()

    def translate(self, header, metadata):
        """
        Main method of the translator: translates a metadata
        record to a :class:`BarePaper`.

        :param header: the OAI-PMH header, as returned by pyoai
        :param metadata: the dictionary of the record, as returned by pyoai
        :returns: a :class:`BarePaper` or None if creation failed
        """
        raise NotImplementedError()


class OAIDCTranslator(OaiTranslator):
    """
    Translator for the default format supplied by OAI-PMH interfaces,
    called oai_dc.
    """

    def format(self):
        return 'oai_dc'

    def get_oai_authors(self, metadata):
        """
        Get the authors names out of a metadata record
        """
        parsed = list(map(parse_comma_name, metadata['creator']))
        names = [BareName.create_bare(fst, lst) for fst, lst in parsed]
        return names

    def find_earliest_oai_date(self, metadata):
        """
        Find the latest publication date (if any) in a record
        """
        earliest = None
        for date in metadata['date']:
            try:
                parsed = tolerant_datestamp_to_datetime(date)
                if not valid_publication_date(parsed):
                    continue
                if earliest is None or parsed < earliest:
                    earliest = parsed
            except (DatestampError, ValueError):
                continue
        return earliest

    def extract_urls(self, header, metadata, source_identifier):
        """
        Extracts URLs from the record,
        based on the identifier of its source.

        The semantics of URLs vary greatly from provider
        to provider, so we build custom rules for each
        of the providers we cover. These rules
        are stored as :class:`URLExtractor`.

        :returns: a pair of URLs or Nones: the splash and
            pdf url. The splash URL is requred (cannot be None)
            and points to the URI where the resource is mentioned.
            This is typically an abstract page.
            The PDF url is non-empty if and only if we think
            a full text is available. If it is possible, this
            URL should point to the full text directly, otherwise
            to a page where we think a human user can find the
            full text by themselves (and for free).
        """
        extractor = REGISTERED_OAI_EXTRACTORS.get(source_identifier, defaultExtractor)
        urls = extractor.extract(header, metadata)
        pdf_url = urls.get('pdf')
        splash_url = urls.get('splash')
        return splash_url, pdf_url

    def translate(self, header, metadata):
        """
        Creates a BarePaper
        """
        # We need three things to create a paper:
        # - publication date
        pubdate = self.find_earliest_oai_date(metadata)
        # - authors
        authors = self.get_oai_authors(metadata)

        # - title
        if not metadata.get('title') or not authors or not pubdate:
            logger.debug("No title, authors or pubdate")
            return

        # Create paper and record
        try:
            paper = BarePaper.create(metadata['title'][0], authors, pubdate)
            self.add_oai_record(header, metadata, paper)
            return paper
        except ValueError as e:
            logger.warning("OAI record %s skipped:\n%s", header.identifier(), e, exc_info=True)
            paper.update_availability()

    def add_oai_record(self, header, metadata, paper):
        """
        Add a record (from OAI-PMH) to the given paper
        """
        identifier = header.identifier()

        # description in oai_dc means abstract
        curdesc = ""
        for desc in metadata['description']:
            if len(desc) > len(curdesc):
                curdesc = desc
        curdesc = sanitize_html(curdesc)

        # Run extractor to find the URLs
        splash_url, pdf_url = self.extract_urls(
            header, metadata, self.oaisource.identifier)

        keywords = ' | '.join(metadata['subject'])
        contributors = ' '.join(metadata['contributor'])[:4096]

        typenorms = ['base:{}'.format(tn) for tn in metadata.get('typenorm', [])]
        pubtype_list = metadata.get('type', []) + typenorms
        pubtype = None
        for raw_pubtype in pubtype_list:
            pubtype = OAI_PUBTYPE_TRANSLATIONS.get(raw_pubtype)
            if pubtype is not None:
                break

        if pubtype is None:
            pubtype = self.oaisource.default_pubtype

        # Find the DOI, if any
        doi = None
        for url in metadata['identifier']+metadata['relation']+metadata['source']:
            if not doi:
                doi = to_doi(url)

        record = BareOaiRecord(
                source=self.oaisource,
                identifier=identifier,
                description=curdesc,
                keywords=keywords,
                contributors=contributors,
                pubtype=pubtype,
                pdf_url=pdf_url,
                splash_url=splash_url,
                doi=doi)
        paper.add_oairecord(record)


class BASEDCTranslator(OAIDCTranslator):
    """
    base_dc is very similar to oai_dc, so we
    don't have much to change
    """

    def format(self):
        return 'base_dc'
