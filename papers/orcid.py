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
from papers.utils import jpath
from papers.utils import urlize


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

    def request_element(self, path):
        """
        Returns the base URL of the profile on the API
        """
        headers = {'Accept': 'application/orcid+json'}
        url = 'https://pub.{instance}/v2.1/{orcid}/{path}'.format(instance=self.instance, orcid=self.id, path=path)
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
        works_summary = self.request_element('works')
        return works_summary.get('group') or []

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
        if name is not None:
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
