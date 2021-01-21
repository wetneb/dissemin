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


import logging
import os
import bz2

from backend.papersource import PaperSource

from django.db import transaction
from multiprocessing_generator import ParallelGenerator
from oaipmh.client import Client

from oaipmh.error import NoRecordsMatchError
from oaipmh.metadata import MetadataRegistry
from oaipmh.metadata import oai_dc_reader
from papers.models import Paper
from papers.models import OaiRecord
from backend.translators import OAIDCTranslator
from backend.translators import BASEDCTranslator
from backend.oaireader import base_dc_reader
from backend.utils import with_speed_report
from backend.utils import group_by_batches

logger = logging.getLogger('dissemin.' + __name__)

class OaiPaperSource(PaperSource):  # TODO: this should not inherit from PaperSource
    """
    A paper source that fetches records from an OAI-PMH source
    (typically: BASE).

    It uses the ListRecord verb to fetch records from the OAI-PMH
    source. Each record is then converted to a :class:`BarePaper`
    by an :class:`OaiTranslator` that handles the format
    the metadata is served in.
    """

    def __init__(self, oaisource, day_granularity=False, *args, **kwargs):
        """
        This sets up the paper source.

        :param oaisource: the OAISource to fetch from.
        :param day_granularity: should we use day-granular timestamps
            to fetch from the proxy or full timestamps (default: False,
            full timestamps)

        See the protocol reference for more information on timestamp
        granularity:
        https://www.openarchives.org/OAI/openarchivesprotocol.html
        """
        super(OaiPaperSource, self).__init__(*args, **kwargs)
        if not oaisource.endpoint:
            raise ValueError('No OAI endpoint was configured for this OAI source.')

        self.registry = MetadataRegistry()
        self.registry.registerReader('oai_dc', oai_dc_reader)
        self.registry.registerReader('base_dc', base_dc_reader)
        self.client = Client(oaisource.endpoint, self.registry)
        self.client._day_granularity = day_granularity
        self.translators = {
            'oai_dc': OAIDCTranslator(oaisource),
            'base_dc': BASEDCTranslator(oaisource),
        }

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

    def ingest(self, from_date=None, metadataPrefix='oai_dc',
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
        self.process_records(records, metadataPrefix)

    def load_base_dump(self, directory_path):
        """
        Given a path to a directory, representing an un-tar'ed BASE dump,
        read all the bz2'ed files in it and save them to the database.

        :param directory_path: the path to the directory where the BASE dump was un-tar'ed
        """
        metadata_prefix = 'base_dc'
        generator = self.read_base_dump(directory_path, metadata_prefix)
        self.process_records(generator, metadata_prefix, max_lookahead=10000)

    def read_base_dump(self, directory_path, metadata_prefix):
        """
        Given a path to a directory, representing an un-tar'ed BASE dump,
        read all the bz2'ed files in it as a generator of OAI records

        :param directory_path: the path to the directory where the BASE dump was un-tar'ed
        :param metadata_prefix: the metadata prefix to read the records
        """
        filenames = os.listdir(directory_path)
        namespaces = self.client.getNamespaces()
        metadata_registry = self.client.getMetadataRegistry()
        for filename in filenames:
            if not filename.endswith('.bz2'):
                continue
            file_path = os.path.join(directory_path, filename)
            with bz2.open(file_path, 'r') as f:
                payload = f.read()
                tree = self.client.parse(payload)
                records, _ = self.client.buildRecords(
                        metadata_prefix, namespaces,
                        metadata_registry, tree)
                for header, metadata, about in records:
                    header._element = None
                    metadata._element = None
                    yield (header, metadata, about)

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
        return self.process_record(record[0], record[1]._map, metadataPrefix)

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

    def translate_record(self, header, metadata, metadata_format):
        """
        Translates a record to a BarePaper. Returns None
        if an invalid format is given, or the record has incomplete metadata.
        """
        translator = self.translators.get(metadata_format)
        if translator is None:
            logger.warning("Unknown metadata format %s, skipping" % header.format())
            return
        return translator.translate(header, metadata)

    def process_record(self, header, metadata, metadata_format):
        """
        Saves the record given by the header and metadata (as returned by
        pyoai) into a Paper, or None if anything failed.
        """
        paper = self.translate_record(header, metadata, metadata_format)

        if paper is not None:
            try:
                with transaction.atomic():
                    saved = Paper.from_bare(paper)
                return saved
            except ValueError:
                logger.exception("Ignoring invalid paper with header %s" % header.identifier())

    def process_records(self, listRecords, metadata_format, max_lookahead=1000):
        """
        Save as :class:`Paper` all the records contained in this list.
        Records are represented as pairs of OaiHeader and OaiRecord, as returned
        by pyoai's ListRecords
        """
        # check that we have at least one translator, otherwise
        # it's not really worth trying…
        if not self.translators:
            raise ValueError("No OAI translators have been set up: " +
                             "We cannot save any record.")

        with ParallelGenerator(listRecords, max_lookahead=max_lookahead) as g:
            for record_group in group_by_batches(with_speed_report(g, name='OAI papers')):
                oai_ids_to_last_updated = {
                    record[0].identifier():record[0].datestamp() for record in record_group
                }

                # Fetch the last modified date of all these records in the DB
                last_modified_in_db = {
                    pk : last_modified
                    for pk, last_modified in OaiRecord.objects.filter(
                        identifier__in=oai_ids_to_last_updated.keys()
                    ).values_list('identifier', 'last_update')
                }

                # Deduce the list of papers to update
                ids_to_update = {
                    pk
                    for pk, last_updated_in_base in oai_ids_to_last_updated.items()
                    if pk not in last_modified_in_db or last_modified_in_db[pk].date() <= last_updated_in_base.date()
                }

                bare_papers = [self.translate_record(record[0], record[1]._map, metadata_format)
                               for record in record_group
                               if record[0].identifier() in ids_to_update]

                for paper in bare_papers:
                    if paper is not None:
                        try:
                            with transaction.atomic():
                                Paper.from_bare(paper)
                        except ValueError:
                            logger.exception("Ignoring invalid paper with identifier ", paper.oairecords[0].identifier)


