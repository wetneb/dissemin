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

from datetime import datetime
import json

from backend.crossref import CrossRefAPI
from backend.extractors import REGISTERED_OAI_EXTRACTORS
from backend.papersource import PaperSource
from backend.pubtype_translations import OAI_PUBTYPE_TRANSLATIONS
from django.conf import settings
from django.db import transaction
from oaipmh import common
from oaipmh.client import Client
from oaipmh.error import DatestampError
from oaipmh.error import NoRecordsMatchError
from oaipmh.metadata import base_dc_reader
from oaipmh.metadata import MetadataReader
from oaipmh.metadata import MetadataRegistry
from oaipmh.metadata import oai_dc_reader
from papers.baremodels import BareName
from papers.baremodels import BareOaiRecord
from papers.baremodels import BarePaper
from papers.doi import to_doi
from papers.models import OaiSource
from papers.models import Paper
from papers.name import parse_comma_name
from papers.utils import sanitize_html
from papers.utils import tolerant_datestamp_to_datetime
from papers.utils import valid_publication_date

# Set exposed by proaixy to indicate the metadata source
PROXY_SOURCE_PREFIX = "proaixy:source:"

def get_proaixy_instance():
    proaixy = OaiPaperSource(endpoint='http://doai.io/oai')
    proaixy.add_translator(BASEDCTranslator())
    proaixy.add_translator(CiteprocTranslator())
    return proaixy

class OaiTranslator(object):
    """
    A translator takes a metadata record from the OAI-PMH
    proxy and converts it to a :class:`BarePaper`.
    """

    def format(self):
        """
        Returns the metadata format expected by the translator
        """
        return 'oai_dc'

    def translate(self, header, metadata):
        """
        Main method of the translator: translates a metadata
        record to a :class:`BarePaper`.

        :param header: the OAI-PMH header, as returned by pyoai
        :param metadata: the dictionary of the record, as returned by pyoai
        :returns: a :class:`BarePaper` or None if creation failed
        """
        raise NotImplementedError()


class CiteprocReader(MetadataReader):

    def __init__(self):
        super(CiteprocReader, self).__init__({}, {})

    def __call__(self, element):
        # extract the Json
        jsontxt = element.text
        payload = json.loads(jsontxt)

        return common.Metadata(element, payload)

citeproc_reader = CiteprocReader()


class CiteprocTranslator(object):
    """
    A translator for the JSON-based Citeproc format served by Crossref
    """

    def __init__(self):
        self.cr_api = CrossRefAPI()

    def format(self):
        return 'citeproc'

    def translate(self, header, metadata):
        try:
            return self.cr_api.save_doi_metadata(metadata)
        except ValueError:
            return


class OAIDCTranslator(object):
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
        parsed = map(parse_comma_name, metadata['creator'])
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
        pdf_url = None
        splash_url = None
        try:
            extractor = REGISTERED_OAI_EXTRACTORS[source_identifier]
            urls = extractor.extract(header, metadata)
            pdf_url = urls.get('pdf')
            splash_url = urls.get('splash')
        except KeyError:
            print "Warning, invalid extractor for source "+source_identifier
        return splash_url, pdf_url

    def get_source(self, header, metadata):
        """
        Find the OAI source to use for this record
        """
        sets = header.setSpec()
        source_identifier = None
        for s in sets:
            if s.startswith(PROXY_SOURCE_PREFIX):
                source_identifier = s[len(PROXY_SOURCE_PREFIX):]
                break
        source = None
        if source_identifier:
            try:
                source = OaiSource.objects.get(identifier=source_identifier)
            except OaiSource.DoesNotExist:
                pass
        return source

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
            #print "no title, authors, or pubdate"
            return

        # Find the OAI source
        source = self.get_source(header, metadata)

        if not source:
            print "Invalid source from the proxy, skipping"
            return

        # Create paper and record
        try:
            paper = BarePaper.create(metadata['title'][0], authors, pubdate)
            self.add_oai_record(header, metadata, source, paper)
            return paper
        except ValueError as e:
            print "Warning, OAI record "+header.identifier()+" skipped:\n"+unicode(e)
            paper.update_availability()

    def add_oai_record(self, header, metadata, source, paper):
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
            header, metadata, source.identifier)

        keywords = ' | '.join(metadata['subject'])
        contributors = ' '.join(metadata['contributor'])[:4096]

        typenorms = ['typenorm:'+tn for tn in metadata.get('typenorm', [])]
        pubtype_list = metadata.get('type', []) + typenorms
        pubtype = None
        for raw_pubtype in pubtype_list:
            pubtype = OAI_PUBTYPE_TRANSLATIONS.get(raw_pubtype)
            if pubtype is not None:
                break

        if pubtype is None:
            pubtype = source.default_pubtype

        # Find the DOI, if any
        doi = None
        for url in metadata['identifier']+metadata['relation']+metadata['source']:
            if not doi:
                doi = to_doi(url)

        record = BareOaiRecord(
                source=source,
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

class CustomSourceOAIDCTranslator(OAIDCTranslator):
    """
    Just like OAIDCTranslator, but with a custom source
    (not assuming that the endpoint is proaixy)
    """
    def __init__(self, source):
        self.source = source

    def get_source(self, header, record):
        return self.source

class OaiPaperSource(PaperSource):  # TODO: this should not inherit from PaperSource
    """
    A paper source that fetches records from the OAI-PMH proxy
    (typically: proaixy).

    It uses the ListRecord verb to fetch records from the OAI-PMH
    source. Each record is then converted to a :class:`BarePaper`
    by an :class:`OaiTranslator` that handles the format
    the metadata is served in.
    """

    def __init__(self, endpoint, day_granularity=False, *args, **kwargs):
        """
        This sets up the paper source.

        :param endpoint: the address of the OAI-PMH endpoint
            to fetch from.
        :param day_granularity: should we use day-granular timestamps
            to fetch from the proxy or full timestamps (default: False,
            full timestamps)

        See the protocol reference for more information on timestamp
        granularity:
        https://www.openarchives.org/OAI/openarchivesprotocol.html
        """
        super(OaiPaperSource, self).__init__(*args, **kwargs)
        self.registry = MetadataRegistry()
        self.registry.registerReader('oai_dc', oai_dc_reader)
        self.registry.registerReader('base_dc', base_dc_reader)
        self.registry.registerReader('citeproc', citeproc_reader)
        self.client = Client(endpoint, self.registry)
        self.client._day_granularity = day_granularity
        if settings.PROAIXY_API_KEY:
            self.client.extra_parameters = {
                'key': settings.PROAIXY_API_KEY}
        self.translators = {}

    # Translator management

    def add_translator(self, translator):
        """
        Adds the given translator to the paper source,
        so that we know how to translate papers in the given format.

        The paper source cannot hold more than one translator
        per OAI format (it decides what translator to use
        solely based on the format) so if there is already a translator
        for that format, it will be overriden.
        """
        self.translators[translator.format()] = translator

    # Record ingestion

    def ingest(self, from_date=None, metadataPrefix='any',
               resumptionToken=None):
        """
        Main method to fill Dissemin with papers!

        :param from_date: only fetch papers modified after that date in
                          the proxy (useful for incremental fetching)
        :param metadataPrefix: restrict the ingest for this metadata
                          format
        """
	args = {'metadataPrefix':metadataPrefix}
	if from_date:
	    args['from_'] = from_date
	if resumptionToken:
	    args['resumptionToken'] = resumptionToken
        records = self.client.listRecords(**args)
        self.process_records(records)

    def create_paper_by_identifier(self, identifier, metadataPrefix):
        """
        Queries the OAI-PMH proxy for a single paper.

        :param identifier: the OAI identifier to fetch
        :param metadataPrefix: the format to use (a translator
                    has to be registered for that format, otherwise
                    we return None with a warning message)
        :returns: a Paper or None
        """
        record = self.client.getRecord(
                    metadataPrefix=metadataPrefix,
                    identifier=identifier)
        return self.process_record(record[0], record[1]._map)

    # Record search utilities

    def listRecords_or_empty(self, source, *args, **kwargs):
        """
        pyoai raises :class:`NoRecordsMatchError` when no records match,
        we would rather like to get an empty list in that case.
        """
        try:
            return source.listRecords(*args, **kwargs)
        except NoRecordsMatchError:
            return []

    def process_record(self, header, metadata):
        """
        Saves the record given by the header and metadata (as returned by
        pyoai) into a Paper, or None if anything failed.
        """
        translator = self.translators.get(header.format())
        if translator is None:
            print("Warning: unknown metadata format %s, skipping" %
                  header.format())
            return

        paper = translator.translate(header, metadata)
        if paper is not None:
            try:
                with transaction.atomic():
                    saved = Paper.from_bare(paper)
                return saved
            except ValueError as e:
                print "Ignoring invalid paper:"
                print header.identifier()
                print e

    def process_records(self, listRecords):
        """
        Save as :class:`Paper` all the records contained in this list
        """
        # check that we have at least one translator, otherwise
        # it's not really worth trying…
        if not self.translators:
            raise ValueError("No OAI translators have been set up: " +
                             "We cannot save any record.")

        last_report = datetime.now()
        processed_since_report = 0

        for record in listRecords:
            header = record[0]
            metadata = record[1]._map

            self.process_record(header, metadata)

            # rate reporting
            processed_since_report += 1
            if processed_since_report >= 1000:
                td = datetime.now() - last_report
                rate = 'infty'
                if td.seconds:
                    rate = unicode(processed_since_report / td.seconds)
                print("current rate: %s records/s" % rate)
                processed_since_report = 0
                last_report = datetime.now()
