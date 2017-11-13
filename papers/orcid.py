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

import requests

from django.conf import settings
from django.utils.http import urlencode
from django.utils.functional import cached_property
from lxml import etree
from papers.errors import MetadataSourceException
from papers.name import normalize_name_words
from papers.name import parse_comma_name
from papers.name import shallower_name_similarity
from papers.name import most_similar_author
from papers.utils import jpath
from papers.utils import urlize
from papers.utils import parse_int
from papers.utils import try_date
from papers.baremodels import BareName
from papers.bibtex import parse_bibtex
from papers.doi import to_doi

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



class OrcidProfile(object):
    """
    An orcid profile as returned by the ORCID public API (in JSON)
    """

    def __init__(self, orcid_id=None, json=None, instance=settings.ORCID_BASE_DOMAIN):
        """
        Create a profile by ORCID ID or by providing directly the parsed JSON payload.
        """
        self.json = json
        self.id = orcid_id
        self.instance = instance
        if self.instance not in ['orcid.org', 'sandbox.orcid.org']:
            raise ValueError('Unexpected instance')

        if orcid_id is not None:
            self.fetch()

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
        return 'https://pub.{instance}/v2.1/{orcid}/'.format(instance=self.instance, orcid=self.id)

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
        This only fetches the summaries, subsequent requests will be made for works.
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
                'The ORCiD {id} could not be found'.format(id=self.id))
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
        works_summary = self.request_element('works')
        for group in works_summary.get('group') or []:
            for summary in group.get('work-summary') or []:
                yield OrcidWorkSummary(summary)

    @property
    def homepage(self):
        """
        Extract an URL for that researcher (if any)
        """
        lst = jpath(
            'person/researcher-urls/researcher-url', self.json, default=[])
        for url in lst:
            val = jpath('url/value', url)
            name = jpath('url-name', url)
            if name is not None and ('home' in name.lower() or 'personal' in name.lower()):
                return urlize(val)
        if len(lst):
            return urlize(jpath('url/value', lst[0])) or None

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
            disamb = jpath('organization/disambiguated-organization',
                affiliation, default={})
            source = disamb.get('disambiguation-source')
            inst_id = disamb.get('disambiguated-organization-identifier')
            name = jpath('organization/name', affiliation)
            country = jpath('organization/address/country', affiliation)
            identifier = None
            # we skip ringgold identifiers, because they suck:
            # https://github.com/ORCID/ORCID-Source/issues/3297
            if source and inst_id and source.lower() != 'ringgold':
                identifier = unicode(source).lower()+'-'+unicode(inst_id)

            if name and country:
                return {
                    'identifier':identifier,
                    'name':name,
                    'country':country,
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
        If there is no such name, returns the given and family names on the profile
        (they should exist)
        """
        name_item = jpath('person/name', self.json)
        name = jpath('credit-name/value', name_item)
        if name:
            return parse_comma_name(name)
        return (normalize_name_words(jpath('given-names/value', name_item, '')),
                normalize_name_words(jpath('family-name/value', name_item, '')))

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
            names.append((normalize_name_words(jpath('name/given-names/value', person, '')),
                          normalize_name_words(jpath('name/family-name/value', person, ''))))
        other_names = jpath('other-names/other-name', person, default=[])
        for name in other_names:
            val = name.get('content')
            if val is not None:
                names.append(parse_comma_name(val))
        return names

    def fetch_works(self, put_codes):
        """
        Retrieves the full metadata of the given works in this profile.
        """
        batch_size = 25
        # TODO
        i = 0
        while i < len(put_codes):
            batch = put_codes[i:(i+batch_size)]
            i += batch_size
            works_meta = self.request_element('works/'+','.join([str(c) for c in batch]))
            for work in works_meta.get('bulk') or []:
                yield OrcidWork(self, work)

    @staticmethod
    def search_by_name(first, last, instance=settings.ORCID_BASE_DOMAIN):
        """
        Searches for an ORCID profile matching this (first,last) name.
        Returns a list of such ORCID profiles.
        """
        # Validate arguments
        if not last:
            return
        # Perform query
        base_base_pub = "https://pub." + instance + "/"
        baseurl = base_base_pub + 'v1.2/search/orcid-bio/'
        dct = {
            'rows': 10,
            'start': 0,
            'q': 'family-name:%s given-names:%s' % (last, first),
            }
        url = baseurl+'?'+urlencode(dct)
        try:
            r = requests.get(url)
            # the namespace is the same for both the production and the
            # sandbox versions.
            ns = {'ns': 'http://www.orcid.org/ns/orcid'}
            xml = etree.fromstring(r.text.encode('utf-8'))
            for elem in xml.xpath('//ns:orcid-search-result', namespaces=ns):
                candidateFirst = None
                candidateLast = None
                # Get name
                pers_details = elem.xpath(
                    './/ns:personal-details', namespaces=ns)
                if not pers_details:
                    continue
                for item in pers_details[0]:
                    if item.tag.endswith('given-names'):
                        candidateFirst = item.text
                    elif item.tag.endswith('family-name'):
                        candidateLast = item.text
                if not candidateFirst or not candidateLast:
                    continue
                # Check that the names are compatible
                if shallower_name_similarity((first, last), (candidateFirst, candidateLast)) == 0:
                    continue

                # Get ORCID iD
                orcid_elem = elem.xpath(
                    './ns:orcid-profile/ns:orcid-identifier/ns:path', namespaces=ns)
                if not orcid_elem:
                    continue
                orcid = orcid_elem[0].text

                # Add other things
                lst = elem.xpath(
                    './ns:orcid-profile/ns:orcid-bio/ns:researcher-urls/ns:researcher-url/ns:url/text()', namespaces=ns)
                homepage = None
                for url in lst:
                    homepage = urlize(url)
                    break

                keywords = elem.xpath(
                    './ns:orcid-profile/ns:orcid-bio/ns:keywords/ns:keyword/text()', namespaces=ns)

                yield {
                        'first': candidateFirst,
                        'last': candidateLast,
                        'orcid': orcid,
                        'homepage': homepage,
                        'keywords': keywords,
                      }

        except etree.XMLSyntaxError as e:
            print e
        except requests.exceptions.RequestException as e:
            print e

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

    def __unicode__(self):
        return self.title

    def __repr__(self):
        return '<OrcidWorkSummary for "{title}">'.format(title=self.title)

class SkippedPaper(Exception):
    pass

class OrcidWork(object):

    def __init__(self, orcid_profile, json):
        self.profile = orcid_profile
        self.json = json
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
        return self.j('work/title/title/value')

    @property
    def pubtype(self):
        return orcid_to_doctype(self.j('work/type', 'other'))

    @property
    def contributors(self):
        def get_contrib(js):
            return {
                    'orcid': jpath('contributor-orcid', js),
                    'name': jpath('credit-name/value', js),
            }

        return map(get_contrib, self.j('work/contributors/contributor', []))

    @property
    def authors_from_contributors(self):
        author_names = [c['name'] for c in self.contributors if c['name'] is not None]
        return map(parse_comma_name, author_names)

    @property
    def authors(self):
        """
        This provides the list of authors, determined from (in order of priority):
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
        year = parse_int(self.j('work/publication-date/year/value'), 1970)
        month = parse_int(self.j('work/publication-date/month/value'), 1)
        day = parse_int(self.j('work/publication-date/day/value'), 1)
        pubdate = try_date(year, month, day) or try_date(
            year, month, 1) or try_date(year, 1, 1)
        if pubdate is None:
            print("Invalid publication date in ORCID publication, skipping")
            raise SkippedPaper("INVALID_PUB_DATE")
        else:
            return pubdate

    @property
    def put_code(self):
        """
        ORCiD internal id for the work
        """
        return self.j('put-code')

    @property
    def api_uri(self):
        """
        URI version of the above
        """
        return self.profile.api_uri + 'work/{put_code}'.format(put_code=self.put_code)

    def orcids(self, authors, initial_orcids):
        return affiliate_author_with_orcid(self.profile.name, self.id, authors, initial_orcids=initial_orcids)

    @property
    def citation_format(self):
        return self.j('work/citation/citation-type')

    @property
    def bibtex(self):
        return self.j('work/citation/citation-value')

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
        orcids = affiliate_author_with_orcid(self.profile.name, self.id, authors)
        names = [BareName.create_bare(first, last)
                for first, last in self.authors]
        names_and_orcids = zip(names, orcids)
        filtered = [(n,o) for n, o in names_and_orcids if  n is not None ]
        final_names = [n for n, o in filtered]
        final_orcids = [o for n, o in filtered]
        return final_names, final_orcids

    def j(self, path, default=None):
        return jpath(path, self.json, default)

    def throw_skipped(self):
        if not self.title:
            raise SkippedPaper('NO_TITLE')

        if not self.authors:
            raise SkippedPaper('NO_AUTHOR')

        if not self.pubdate:
            raise SkippedPaper('NO_PUBDATE')

    def __repr__(self):
        return '<ORCIDDataPaper %s written by %s>' % (self.title, ', '.join(self.authors))

    def __str__(self):
        return self.title

    @property
    def splash_url(self):
        return 'https://{}/{}'.format(settings.ORCID_BASE_DOMAIN, self.id)

    def as_dict(self):
        return self.__dict__


