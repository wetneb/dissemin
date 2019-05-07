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


import logging
import os
import re
import requests

from django.conf import settings
from django.utils.functional import cached_property
from lxml import etree as ET
from papers.errors import MetadataSourceException
from papers.name import normalize_name_words
from papers.name import parse_comma_name
from papers.name import most_similar_author
from papers.utils import jpath
from papers.utils import urlize
from papers.utils import parse_int
from papers.utils import try_date
from papers.baremodels import BareName
from papers.bibtex import parse_bibtex
from papers.doi import to_doi

logger = logging.getLogger('dissemin.' + __name__)

NAMESPACE_REGEX = re.compile('{.*?}')

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


def orcid_to_doctype(typ):
    return orcid_type_to_pubtype.get(
        typ.lower().replace('_', '-').replace(' ', '-'),
        'other'
    )


def affiliate_author_with_orcid(ref_name, orcid, authors, initial_orcids=None):
    """
    Given a reference name and an ORCiD for a researcher, find out which
    author in the list is the most likely to be that author. This function
    is run on author lists of papers listed in the ORCiD record so we expect
    that one of the authors should be the same person as the ORCiD holder.
    This just finds the most similar name and returns the appropriate orcids
    list (None everywhere except for the most similar name where it is the
    ORCiD).
    """
    max_sim_idx = most_similar_author(ref_name, authors)
    orcids = [None]*len(authors)
    if initial_orcids and len(initial_orcids) == len(authors):
        orcids = initial_orcids
    if max_sim_idx is not None:
        orcids[max_sim_idx] = orcid
    return orcids


class OrcidProfile(object):
    """
    An orcid profile as returned by the ORCID public API (in JSON)
    """

    def __init__(
            self, orcid_id=None, json=None, instance=settings.ORCID_BASE_DOMAIN
    ):
        """
        Create a profile by ORCID ID or by providing directly the parsed JSON
        payload.
        """
        self.json = json
        self.id = orcid_id
        self.instance = instance
        if self.instance not in ['orcid.org', 'sandbox.orcid.org']:
            raise ValueError('Unexpected instance')

        if orcid_id is not None and not json:
            self.fetch()

        if json and not self.id:
            self.id = json['orcid-identifier']['path']

    def __getitem__(self, key):
        return self.json[key]

    def __iter__(self):
        return self.json.__iter__()

    def __contains__(self, key):
        return self.json.__contains__(key)

    def get(self, *args, **kwargs):
        return self.json.get(*args, **kwargs)

    def __repr__(self):
        return "<OrcidProfile for {orcid}>".format(orcid=self.id)

    @property
    def api_uri(self):
        """
        URI of the profile in the ORCid API
        """
        return 'https://pub.{instance}/v2.1/{orcid}/'.format(
            instance=self.instance, orcid=self.id
        )

    def request_element(self, path):
        """
        Returns the base URL of the profile on the API
        """
        headers = {'Accept': 'application/orcid+json'}
        url = self.api_uri + path
        return requests.get(url, headers=headers).json()

    def fetch(self):
        """
        Fetches the profile by id using the public API.
        This only fetches the summaries, subsequent requests will be made for
        works.
        """
        try:
            parsed = self.request_element('')
            if parsed.get('orcid-identifier') is None:
                # TEMPORARY: also check from the sandbox
                if self.instance == 'orcid.org':
                    self.instance = 'sandbox.orcid.org'
                    return self.fetch()
                raise ValueError
            self.json = parsed
        except (requests.exceptions.HTTPError, ValueError):
            raise MetadataSourceException(
                'The ORCiD {id} could not be found from {instance}'.format(
                    id=self.id, instance=self.instance
                )
            )
        except TypeError:
            raise MetadataSourceException(
                'The ORCiD {id} returned invalid JSON.'.format(id=self.id))

    @cached_property
    def work_summaries(self):
        """
        These represent striped-down versions of the works in the 2.0 API.
        """
        return list(self._work_summaries_generator())

    def _work_summaries_generator(self):
        if self.json is not None:
            works_summary = jpath(
                'activities-summary/works', self.json
            ) or {}
        else:
            works_summary = self.request_element('works')
        # Note: the 'or []' are required below to take into account None
        # values.
        for group in works_summary.get('group') or []:
            for summary in group.get('work-summary') or []:
                yield OrcidWorkSummary(summary)

    @property
    def homepage(self):
        """
        Extract an URL for that researcher (if any)
        """
        lst = jpath(
            'person/researcher-urls/researcher-url',
            self.json,
            default=[]
        )
        for url in lst:
            val = jpath('url/value', url)
            name = jpath('url-name', url)
            if (
                    name is not None
                    and ('home' in name.lower() or 'personal' in name.lower())
            ):
                return urlize(val)
        if lst:
            return urlize(jpath('url/value', lst[0])) or None
        return None

    @property
    def institution(self):
        """
        The name and identifier of the latest institution associated
        with this researcher
        """
        lst = jpath(
            'activities-summary/employments/employment-summary',
            self.json, default=[])
        lst += jpath(
            'activities-summary/educations/education-summary',
            self.json, default=[])

        for affiliation in lst:
            disamb = jpath(
                'organization/disambiguated-organization',
                affiliation,
                default={}
            )
            source = disamb.get('disambiguation-source')
            inst_id = disamb.get('disambiguated-organization-identifier')
            name = jpath('organization/name', affiliation)
            country = jpath('organization/address/country', affiliation)
            identifier = None
            # we skip ringgold identifiers, because they suck:
            # https://github.com/ORCID/ORCID-Source/issues/3297
            if source and inst_id and source.lower() != 'ringgold':
                identifier = str(source).lower()+'-'+str(inst_id)

            if name and country:
                return {
                    'identifier': identifier,
                    'name': name,
                    'country': country,
                }
        return None

    @property
    def email(self):
        # TODO
        return None

    @property
    def name(self):
        """
        Returns a parsed version of the "credit name" in the ORCID profile.
        If there is no such name, returns the given and family names on the
        profile (they should exist)
        """
        name_item = jpath('person/name', self.json)
        name = jpath('credit-name/value', name_item)
        if name:
            return parse_comma_name(name)
        return (
            normalize_name_words(jpath('given-names/value', name_item, '')),
            normalize_name_words(jpath('family-name/value', name_item, ''))
        )

    @property
    def other_names(self):
        """
        Returns the list of other names listed on the ORCiD profile.
        This includes the (given,family) name if a credit name was defined.
        """
        person = jpath('person', self.json)
        names = []
        credit_name = jpath('name/credit-name/value', person)
        if credit_name is not None:
            names.append(
                (
                    normalize_name_words(
                        jpath('name/given-names/value', person, '')
                    ),
                    normalize_name_words(
                        jpath('name/family-name/value', person, '')
                    )
                )
            )
        other_names = jpath('other-names/other-name', person, default=[])
        for name in other_names:
            val = name.get('content')
            if val is not None:
                names.append(parse_comma_name(val))
        return names

    def fetch_works(self, put_codes, works_dumps_path=None):
        """
        Retrieves the full metadata of the given works in this profile.

        :param works_dumps_path: Path to a dump of XML files for each work of
            the profile. If provided, ``fetch_works`` uses this dump and avoid
            making API calls to ORCID.
        """
        # Use local folder if available
        if works_dumps_path:
            for put_code in put_codes:
                fpath = os.path.join(
                    works_dumps_path,
                    '%s_works_%s.xml' % (self.id, put_code)
                )
                try:
                    with open(fpath, 'rb') as fh:
                        yield OrcidWork(self, xml_representation=fh.read())
                except IOError:
                    pass
        # Batch query the API otherwise
        else:
            batch_size = 25
            i = 0
            while i < len(put_codes):
                batch = put_codes[i:(i+batch_size)]
                i += batch_size
                works_meta = self.request_element(
                    'works/' + ','.join([str(c) for c in batch])
                )
                for work in works_meta.get('bulk') or []:
                    yield OrcidWork(self, json_representation=work)


class OrcidWorkSummary(object):
    """
    In the 2.0 API ORCID returns "summaries" of publications, where not all the
    metadata is included: this class represents that.
    """

    def __init__(self, json):
        """
        :param json: the JSON representation of the summary
        """
        self.json = json

    @property
    def doi(self):
        """
        Returns the DOI of this publication, if any.
        """
        for external_id in jpath('external-ids/external-id', self.json, []):
            if (external_id.get('external-id-type') == 'doi' and
                external_id.get('external-id-relationship') == 'SELF' and
                external_id.get('external-id-value')):
                doi = to_doi(external_id.get('external-id-value'))
                if doi:
                    return doi
        return None

    @property
    def title(self):
        """
        Returns the title of this publication (always provided)
        """
        return jpath('title/title/value', self.json)

    @property
    def put_code(self):
        return self.json.get('put-code')

    def __str__(self):
        return self.title or '(no title)'

    def __repr__(self):
        return '<OrcidWorkSummary for "{title}">'.format(title=self.title or '(no title)')

class SkippedPaper(Exception):
    pass

class OrcidWork(object):

    def __init__(self, orcid_profile, json_representation=None, xml_representation=None):
        if json_representation is None and xml_representation is None:
            raise TypeError('One of JSON or XML representation should be provided.')
        self.profile = orcid_profile
        self.json = json_representation
        self.xml = xml_representation
        if self.xml is not None:
            self.xml = ET.fromstring(self.xml)
        self.id = orcid_profile.id

        self.skipped = False
        self.skip_reason = None
        try:
            self.throw_skipped()
        except SkippedPaper as e:
            self.skipped = True
            self.skip_reason, = e.args

    @property
    def title(self):
        return self.j('{http://www.orcid.org/ns/work}title/{http://www.orcid.org/ns/common}title/value')

    @property
    def pubtype(self):
        return orcid_to_doctype(
            self.j('{http://www.orcid.org/ns/work}type', 'other')
        )

    @property
    def contributors(self):
        if self.json is not None:
            def get_contrib(js):
                return {
                    'orcid': jpath('contributor-orcid', js),
                    'name': jpath('credit-name/value', js),
                }

            return list(
                map(
                    get_contrib,
                    self.j('{http://www.orcid.org/ns/work}contributors/{http://www.orcid.org/ns/work}contributor', [])
                )
            )
        elif self.xml is not None:
            contributors = []
            items = self.xml.findall(
                '{http://www.orcid.org/ns/work}contributors/{http://www.orcid.org/ns/work}contributor'
            )
            for item in items:
                name = item.find('{http://www.orcid.org/ns/work}credit-name')
                if name is not None:
                    name = name.text

                orcid = item.find(
                    '{http://www.orcid.org/ns/common}contributor-orcid/{http://www.orcid.org/ns/common}path'
                )
                if orcid is not None:
                    orcid = orcid.text

                contributors.append({
                    'orcid': orcid,
                    'name': name,
                })
            return contributors

    @property
    def authors_from_contributors(self):
        author_names = [
            c['name']
            for c in self.contributors
            if c['name'] is not None
        ]
        return list(map(parse_comma_name, author_names))

    @property
    def authors(self):
        """
        This provides the list of authors, determined from (in order of
        priority):
        - the "contributors" field
        - the BibTeX record
        - using the researcher represented by the profile as single author

        :returns: a list of names represented as string pairs
        """
        return (self.authors_from_contributors or
                self.authors_from_bibtex or
                [self.profile.name])

    @property
    def pubdate(self):
        # Pubdate
        # Remark(RaitoBezarius): we don't want to put 01 ; it could be
        # interpreted as octal 1.
        year = parse_int(
            self.j('{http://www.orcid.org/ns/common}publication-date/{http://www.orcid.org/ns/common}year/value'),
            1970
        )
        month = parse_int(
            self.j('{http://www.orcid.org/ns/common}publication-date/{http://www.orcid.org/ns/common}month/value'),
            1
        )
        day = parse_int(
            self.j('{http://www.orcid.org/ns/common}publication-date/{http://www.orcid.org/ns/common}day/value'),
            1
        )
        pubdate = (
            try_date(year, month, day)
            or try_date(year, month, 1) or
            try_date(year, 1, 1)
        )
        if pubdate is None:
            logger.info(
                "Invalid publication date in ORCID publication, skipping"
            )
            raise SkippedPaper("INVALID_PUB_DATE")
        else:
            return pubdate

    @property
    def put_code(self):
        """
        ORCiD internal id for the work
        """
        return self.j('@put-code')

    @property
    def api_uri(self):
        """
        URI version of the above
        """
        return (
            self.profile.api_uri +
            'work/{put_code}'.format(put_code=self.put_code)
        )

    def orcids(self, authors, initial_orcids):
        return affiliate_author_with_orcid(
            self.profile.name,
            self.id,
            authors,
            initial_orcids=initial_orcids
        )

    @property
    def citation_format(self):
        return self.j('{http://www.orcid.org/ns/work}citation/{http://www.orcid.org/ns/work}citation-type')

    @property
    def bibtex(self):
        return self.j('{http://www.orcid.org/ns/work}citation/{http://www.orcid.org/ns/work}citation-value')

    @property
    def authors_from_bibtex(self):
        if self.bibtex is not None:
            try:
                entry = parse_bibtex(self.bibtex)
                if 'author' not in entry or len(entry['author']) == 0:
                    return []
                else:
                    return entry['author']
            except ValueError:
                return []
        else:
            return []

    @property
    def authors_and_orcids(self):
        """
        :returns: two lists of equal length, the first with BareName objects
            representing authors, the second with ORCID ids (or None) for
            each of these authors
        """
        authors = self.authors
        orcids = affiliate_author_with_orcid(
            self.profile.name, self.id, authors
        )
        names = [
            BareName.create_bare(first, last)
            for first, last in self.authors
        ]
        names_and_orcids = list(zip(names, orcids))
        filtered = [(n, o) for n, o in names_and_orcids if n is not None]
        final_names = [n for n, o in filtered]
        final_orcids = [o for n, o in filtered]
        return final_names, final_orcids

    def j(self, path, default=None):
        if self.json is not None:
            # Replace attributes path
            path = path.lstrip('@')
            # Prepend root for JSON
            path = 'work/%s' % path
            # Remove namespaces for JSON
            path = NAMESPACE_REGEX.sub('', path)
            return jpath(path, self.json, default)
        elif self.xml is not None:
            # Handle attributes path
            if path.startswith('@'):
                return self.xml.attrib.get(path.lstrip('@'), default)
            # Remove useless '/value' in XML path
            path = path.replace('/value', '')
            # Get value
            item = self.xml.find(path)
            if item is not None:
                return item.text
            return default

    def throw_skipped(self):
        if not self.title:
            raise SkippedPaper('NO_TITLE')

        if not self.authors:
            raise SkippedPaper('NO_AUTHOR')

        if not self.pubdate:
            raise SkippedPaper('NO_PUBDATE')

    def __repr__(self):
        return '<OrcidWord %s written by %s>' % (
            self.title or '(no title)',
            ', '.join(self.authors)
        )

    def __str__(self):
        return self.title

    @property
    def splash_url(self):
        return 'https://{}/{}'.format(settings.ORCID_BASE_DOMAIN, self.id)

    def as_dict(self):
        return {
            'json': self.json,
            'xml': (
                ET.tostring(self.xml, encoding='unicode')
                if self.xml is not None
                else None
            ),
            'skipped': self.skipped,
            'skip_reason': self.skip_reason
        }


