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

"""
This module defines a OAfr/TEI exporter, to be used with the SWORD interface to HAL.

"""

from __future__ import unicode_literals

from deposit.sword.metadata import addChild
from deposit.sword.metadata import MetadataFormatter
from django.utils.translation import ugettext_lazy as _
from lxml import etree
from papers.models import Paper

HAL_TOPIC_CHOICES = [
    ('CHIM', _('Chemistry')),
    ('INFO', _('Computer science')),
    ('MATH', _('Mathematics')),
    ('PHYS', _('Physics')),
    ('NLIN', _('Non-linear science')),
    ('SCCO', _('Cognitive science')),
    ('SDE', _('Environment sciences')),
    ('SDU', _('Planet and Universe')),
    ('SHS', _('Humanities and Social Science')),
    ('SDV', _('Life sciences')),
    ('SPI', _('Engineering sciences')),
    ('STAT', _('Statistics')),
    ('QFIN', _('Economy and quantitative finance')),
    ('OTHER', _('Other')),
  ]

ENS_HAL_ID = 59704

XMLLANG_ATTRIB = '{http://www.w3.org/XML/1998/namespace}lang'


def aofrDocumentType(paper):
    tr = {
            'journal-article': 'ART',
            'proceedings-article': 'COMM',
            'book-chapter': 'COUV',
            'book': 'OUV',
            'journal-issue': 'DOUV',
            'proceedings': 'DOUV',
            'reference-entry': 'OTHER',
            'poster': 'POSTER',
            'report': 'REPORT',
            'thesis': 'THESE',
            'dataset': 'OTHER',
            'preprint': 'UNDEFINED',
            'other': 'OTHER',
         }
    return tr[paper.doctype]


class AOFRFormatter(MetadataFormatter):
    """
    Formatter for HAL
    """

    def formatName(self):
        return "AOfr"

    def render(self, paper, filename, form):
        xmlns_uri = 'http://www.tei-c.org/ns/1.0'
        xmlns = '{%s}' % xmlns_uri
        nsmap = {None: xmlns_uri, 'hal': 'http://hal.archives-ouvertes.fr'}
        tei = etree.Element(xmlns+'TEI', nsmap=nsmap)
        text = addChild(tei, 'text')
        body = addChild(text, 'body')
        listBibl = addChild(body, 'listBibl')
        biblFull = addChild(listBibl, 'biblFull')

        # titleStmt
        titleStmt = addChild(biblFull, 'titleStmt')

        self.renderTitleAuthors(titleStmt, paper)

        # editionStmt
        if filename != None:
            editionStmt = addChild(biblFull, 'editionStmt')
            edition = addChild(editionStmt, 'edition')
            date = addChild(edition, 'date')
            date.attrib['type'] = 'whenWritten'
            date.text = str(paper.pubdate.year)
            ref = addChild(edition, 'ref')
            ref.attrib['type'] = 'file'
            ref.attrib['subtype'] = 'author'  # TODO adapt based on form info
            ref.attrib['target'] = filename

        # publicationStmt
        # publicationStmt = addChild(biblFull, 'publicationStmt')
        # TODO add license here

        # seriesStmt
        seriesStmt = addChild(biblFull, 'seriesStmt')
        idno = addChild(seriesStmt, 'idno')
        idno.attrib['type'] = 'stamp'
        idno.attrib['n'] = 'ENS-PARIS'
        # TODO add other stamps here (based on the institutions)

        # notesStmt
        notesStmt = addChild(biblFull, 'notesStmt')
        note = addChild(notesStmt, 'note')
        note.attrib['type'] = 'popular'
        note.attrib['n'] = '0'
        note = addChild(notesStmt, 'note')
        note.attrib['type'] = 'audience'
        note.attrib['n'] = '3'
        note = addChild(notesStmt, 'note')
        note.attrib['type'] = 'peer'
        note.attrib['n'] = '1'

        # sourceDesc
        sourceDesc = addChild(biblFull, 'sourceDesc')
        biblStruct = addChild(sourceDesc, 'biblStruct')
        analytic = addChild(biblStruct, 'analytic')

        self.renderTitleAuthors(analytic, paper)

        halType = aofrDocumentType(paper)
        for publication in paper.publications:
            self.renderPubli(biblStruct, publication, halType)

        # profileDesc
        profileDesc = addChild(biblFull, 'profileDesc')
        langUsage = addChild(profileDesc, 'langUsage')
        language = addChild(langUsage, 'language')
        language.attrib['ident'] = 'en'  # TODO adapt this?
        textClass = addChild(profileDesc, 'textClass')

        domains = []
        if 'cleaned_data' in dir(form):
            domains = [form.cleaned_data['topic'].lower()]
        
        for domain in domains:
            classCode = addChild(textClass, 'classCode')
            classCode.attrib['scheme'] = 'halDomain'
            classCode.text = domain
        typology = addChild(textClass, 'classCode')
        typology.attrib['scheme'] = 'halTypology'
        typology.attrib['n'] = halType

        abstract = addChild(profileDesc, 'abstract')
        abstract.attrib[XMLLANG_ATTRIB] = 'en'
        abstract.text = 'No abstract.'
        for record in paper.sorted_oai_records:
            if record.description:
                abstract.text = record.description
                break

        # back = addChild(text, 'back')

        return tei

    def renderTitleAuthors(self, root, paper):
        title = addChild(root, 'title')
        title.attrib[XMLLANG_ATTRIB] = 'en'  # TODO: autodetect language?
        title.text = paper.title

        for author in paper.authors:
            node = addChild(root, 'author')
            node.attrib['role'] = 'aut'
            nameNode = addChild(node, 'persName')

            name = author.name
            curtype = 'first'
            for first in name.first.split(' '):
                forename = addChild(nameNode, 'forename')
                forename.attrib['type'] = curtype
                forename.text = first
                curtype = 'middle'

            lastName = addChild(nameNode, 'surname')
            lastName.text = name.last

            # TODO affiliations come here
            # if author.researcher_id:
            affiliation = addChild(node, 'affiliation')
            affiliation.attrib['ref'] = '#struct-'+str(ENS_HAL_ID)

    def renderPubli(self, biblStruct, publi, halType):
        # TODO: handle publication type properly
        root = addChild(biblStruct, 'monogr')
        if publi.journal:
            self.renderJournal(root, publi.journal)

        title = addChild(root, 'title')
        if halType == 'COUV' or halType == 'OUV' or halType == 'COMM':
            title.attrib['level'] = 'm'
        else:
            title.attrib['level'] = 'j'
        title.text = publi.full_journal_title()

        imprint = addChild(root, 'imprint')

        if publi.publisher:
            publisher = addChild(imprint, 'publisher')
            publisher.text = unicode(publi.publisher)
        if publi.issue:
            biblScope = addChild(imprint, 'biblScope')
            biblScope.attrib['unit'] = 'issue'
            biblScope.text = publi.issue
        if publi.volume:
            biblScope = addChild(imprint, 'biblScope')
            biblScope.attrib['unit'] = 'volume'
            biblScope.text = publi.volume
        if publi.pages:
            biblScope = addChild(imprint, 'biblScope')
            biblScope.attrib['unit'] = 'pp'
            biblScope.text = publi.pages
        if publi.doi:
            idno = addChild(biblStruct, 'idno')
            idno.attrib['type'] = 'doi'
            idno.text = publi.doi

        data = addChild(imprint, 'date')
        data.attrib['type'] = 'datePub'
        data.text = 'unknown'
        if publi.pubdate:
            # TODO output more precise date if available
            data.text = str(publi.pubdate.year)
        else:
            data.text = str(publi.about.pubdate.year)

    def renderJournal(self, root, journal):
        pass


# The following lines are for testing purposes only
def generate(theId):
    formatter = AOFRFormatter()
    paper = Paper.objects.get(pk=theId)
    return formatter.toString(paper, 'article.pdf', True)
