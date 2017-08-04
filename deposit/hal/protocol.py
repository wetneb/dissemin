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

from __future__ import unicode_literals

from io import BytesIO
import json
import traceback
from zipfile import ZipFile
from papers.utils import extract_domain

import requests
from urlparse import urlparse

from deposit.hal.forms import HALForm
from deposit.hal.forms import HALPreferencesForm
from deposit.hal.metadata import AOFRFormatter
from deposit.protocol import DepositError
from deposit.protocol import DepositResult
from deposit.protocol import RepositoryProtocol
from deposit.registry import protocol_registry
from django.utils.translation import ugettext as __
from papers.name import most_similar_author
import defusedxml as etree
from papers.utils import kill_html
from deposit.hal.models import HALDepositPreferences

try:
    import http.client as http_client
except ImportError:
    # Python 2
    import httplib as http_client


#http_client.HTTPConnection.debuglevel = 1


class HALProtocol(RepositoryProtocol):
    """
    A protocol to submit using the HAL SWORD API
    """

    form_class = HALForm
    preferences_form_class = HALPreferencesForm
    preferences_model = HALDepositPreferences

    def __init__(self, repository, **kwargs):
        super(HALProtocol, self).__init__(repository, **kwargs)
        # We let the interface define another API endpoint (sandbox…)
        self.api_url = repository.endpoint
        # for prod: "https://api.archives-ouvertes.fr/sword/"
        # for test: "https://api-preprod.archives-ouvertes.fr/sword/"
        self.username = repository.username
        self.password = repository.password

    def init_deposit(self, paper, user):
        """
        We reject in advance papers that are already in HAL
        """
        super(HALProtocol, self).init_deposit(paper,user)
        for r in paper.oairecords:
            domain = extract_domain(r.splash_url) or ''
            if ('oai:HAL:' in r.identifier or
                domain.endswith('archives-ouvertes.fr')):
                return False

        self.hal_preferences = self.get_preferences(user)
        return True

    def predict_topic(self, topic_text):
        if not topic_text:
            return
        try:
            r = requests.post(
                'http://haltopics.dissem.in:6377/predict', data={'text': topic_text}, timeout=10)
            return r.json()['decision']['code']
        except (requests.exceptions.RequestException, ValueError, KeyError):
            return None

    def get_form_initial_data(self):
        data = super(HALProtocol, self).get_form_initial_data()

        data['first_name'] = self.user.first_name
        data['last_name'] = self.user.last_name

        # Abstract
        if self.paper.abstract:
            data['abstract'] = kill_html(self.paper.abstract)
        else:
            self.paper.consolidate_metadata(wait=False)

        # Topic
        topic_text = ''
        if 'abstract' in data:
            topic_text = data['abstract']
        else:
            topic_text = self.paper.title
        data['topic'] = self.predict_topic(topic_text)
        if data['topic'] == 'OTHER':
            del data['topic']

        # Depositing author
        most_similar_idx = None
        first, last = (self.user.first_name, self.user.last_name)
        if first and last:
            most_similar_idx = most_similar_author((first,last),
                self.paper.author_name_pairs())
        data['depositing_author'] = most_similar_idx

        return data

    def create_zip(self, pdf, metadata):
        s = BytesIO()
        with ZipFile(s, 'w') as zipFile:
            zipFile.write(pdf, "article.pdf")
            zipFile.writestr("meta.xml", str(metadata))
        return s

    def encodeUserData(self):
        return "Basic " + (self.username + ":" + self.password
                           ).encode("base64").rstrip()

    def submit_deposit(self, pdf, form, dry_run=False):
        if self.username is None or self.password is None:
            raise DepositError(__("No HAL user credentials provided."))

        deposit_result = DepositResult()

        try:
            # Creating the metadata
            self.log("### Generating metadata")
            metadata = self.create_metadata(form)

            # Bundling the metadata and the PDF
            self.log("### Creating ZIP file")
            zipFile = self.create_zip(pdf, metadata)

            # Build the list of users who should own this deposit
            on_behalf_of = [self.username]
            if self.hal_preferences.on_behalf_of:
                on_behalf_of.append(self.hal_preferences.on_behalf_of)

            # Creating a new deposition
            self.log("### Creating a new deposition")

            parsed_endpoint = urlparse(self.api_url)
            host = parsed_endpoint.netloc
            path = parsed_endpoint.path + 'hal'

            conn = http_client.HTTPConnection(host)
            conn.putrequest('POST', path, True, True)
            zipContent = zipFile.getvalue()
            headers = {
                'Authorization': self.encodeUserData(),
                'Host': host,
                'X-Packaging': 'http://purl.org/net/sword-types/AOfr',
                'Content-Type': 'application/zip',
                'Content-Disposition': 'attachment; filename=meta.xml',
                'Content-Length': len(zipContent),
                'On-Behalf-Of': ';'.join(on_behalf_of),
                }
            for header, value in headers.items():
                conn.putheader(header, value)
            conn.endheaders()
            conn.send(zipContent)
            resp = conn.getresponse()

            xml_response = resp.read()
            conn.close()
            try:
                parser = etree.XMLParser(encoding='utf-8')
                receipt = etree.parse(BytesIO(xml_response), parser)
                if resp.status != 201:
                    self.log('Deposit response status: HTTP %d' % resp.status)
                    self.log(xml_response.decode('utf-8'))
                    # Get the verbose description of the error to output it as well
                    root = receipt.getroot()
                    verboseDescription = (
                        next(
                            root.iter(
                                "{http://purl.org/net/sword/error/}verboseDescription"
                            )
                        ).text
                    )
                    try:
                        # Give a better error message to the user if the document
                        # already exists in HAL. See #356.
                        assert "duplicate-entry" in json.loads(verboseDescription)
                        raise DepositError(
                            __(
                                'This document is already in HAL. '
                                'HAL refused the deposit.'
                            )
                        )
                    except (ValueError, AssertionError):
                        raise DepositError(
                            __(
                                'HAL refused the deposit (HTTP error %d): %s') %
                                (resp.status, verboseDescription)
                            )
            except etree.XMLSyntaxError:
                self.log('Invalid XML response from HAL:')
                self.log(xml_response.decode('utf-8'))
                self.log('(end of the response)')
                raise DepositError(__('HAL returned an invalid XML response'))

            receipt = receipt.getroot()
            if receipt.tag == '{http://purl.org/net/sword/error/}error':
                self.log('Error while depositing the content.')
                verbosedesc = receipt.find(
                    '{http://purl.org/net/sword/error/}verboseDescription')

                # this will happen if a paper has not made its way via
                # OAI to us, so we could not detect that earlier in the
                # submission
                if verbosedesc is not None and 'duplicate-entry' in verbosedesc.text:
                    raise DepositError(__('This paper already exists in HAL.'))

                # Otherwise this error should not happen: let's dump
                # everything to check later
                self.log('Here is the XML response:{}'.format(xml_response.decode('utf-8')))
                self.log('Here is the metadata:{}'.format(metadata.decode('utf-8')))
                raise DepositError(__('HAL rejected the submission.'))
            else:
                self.log(xml_response)

            deposition_id = receipt.find('{http://www.w3.org/2005/Atom}id').text
            password = receipt.find(
                '{http://hal.archives-ouvertes.fr/}password').text
            document_url = resp.getheader('location')

            if not deposition_id:
                raise DepositError(__('HAL rejected the submission'))

            self.log("Deposition id: %s" % deposition_id)

            deposit_result.identifier = deposition_id
            deposit_result.splash_url = document_url
            deposit_result.pdf_url = None
            deposit_result.status = 'pending' # HAL moderates submissions
            deposit_result.additional_info = [
                {'label':__('Password'),
                 'value':password},
            ]

            if dry_run:
                conn = http_client.HTTPConnection(host)
                conn.putrequest('DELETE', '/sword/'+deposition_id)
                headers = {
                    'Authorization': self.encodeUserData(),
                   # 'Host': host,
                    'Accept': '*/*',
                    'User-Agent': 'dissemin',
                }
                for header, value in headers.items():
                    conn.putheader(header, value)
                conn.endheaders()
                resp = conn.getresponse()
                self.log(resp.read())
                conn.close()
                deposit_result.status = 'faked'

        except DepositError as e:
            raise e
        except Exception as e:
            self.log("Caught exception:")
            self.log(str(type(e))+': '+str(e)+'')
            self.log(traceback.format_exc())
            raise DepositError(__(
                'Connection to HAL failed. Please try again later.'))

        return deposit_result

    def create_metadata(self, form):
        formatter = AOFRFormatter()
        metadata = formatter.toString(self.paper, 'article.pdf',
                                      form, pretty=True)
        return metadata

    def refresh_deposit_status(self, deposit_record):
        """
        Only refresh the status if we don't already know that
        the paper is published - in that case we trust HAL not
        to delete it. This is to reduce the number of requests
        on their side.
        """
        if deposit_record.status != 'published':
            new_status = self.get_new_status(deposit_record.identifier)
            if new_status != deposit_record.status:
                deposit_record.status = new_status
                deposit_record.save(update_fields=['status'])
                oairecord = deposit_record.oairecord
                if new_status == 'published':
                    oairecord.pdf_url = oairecord.splash_url + '/document'
                else:
                    oairecord.pdf_url = None
                oairecord.save(update_fields=['pdf_url'])
                oairecord.about.update_availability()
                oairecord.about.update_index()

    def get_new_status(self, identifier):
        """
        Unconditionnally fetch the new status of a deposit, by ID (e.g.
        hal-0001234)
        """
        deposit_url = '%s%s' % (self.api_url, identifier)
        req = requests.get(deposit_url,
                auth=requests.auth.HTTPBasicAuth(self.username,self.password))
        if req.status_code == 400:
            return 'deleted'
        req.raise_for_status()

        parser = etree.XMLParser(encoding='utf-8')
        receipt = etree.parse(BytesIO(req.text.encode('utf-8')), parser)
        receipt = receipt.getroot()

        hal_status = receipt.find('status').text
        if hal_status == 'accept' or hal_status == 'replace':
            return 'published'
        elif hal_status == 'verify' or hal_status == 'update':
            return 'pending'
        elif hal_status == 'delete':
            return 'refused'


protocol_registry.register(HALProtocol)

