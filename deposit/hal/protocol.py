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
import traceback
from zipfile import ZipFile

import requests

from deposit.hal.forms import HALForm
from deposit.hal.metadata import AOFRFormatter
from deposit.protocol import DepositError
from deposit.protocol import DepositResult
from deposit.protocol import RepositoryProtocol
from deposit.registry import protocol_registry
from django.utils.translation import ugettext as __
from lxml import etree
from papers.utils import kill_html

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

    def __init__(self, repository, **kwargs):
        super(HALProtocol, self).__init__(repository, **kwargs)
        # We let the interface define another API endpoint (sandbox…)
        self.api_url = repository.endpoint
        if not self.api_url:
            self.api_url = "https://api.archives-ouvertes.fr/sword/hal/"
        self.username = repository.username
        self.password = repository.password

    def predict_topic(self, topic_text):
        if not topic_text:
            return
        try:
            r = requests.post(
                'http://haltopics.dissem.in:6377/predict', data={'text': topic_text})
            return r.json()['decision']['code']
        except (requests.exceptions.RequestException, ValueError, KeyError):
            return None

    def get_form(self):
        data = {}
        data['paper_id'] = self.paper.id

        # Abstract
        if self.paper.abstract:
            data['abstract'] = kill_html(self.paper.abstract)
        # commenting this else branch because
        # it introduces a runtime dependency to the redis database
        # however, it is good to be able to run the HAL tests
        # with a simple django config
        #else:
            # self.paper.consolidate_metadata(wait=False)

        # Topic
        topic_text = ''
        if 'abstract' in data:
            topic_text = data['abstract']
        else:
            topic_text = self.paper.title
        data['topic'] = self.predict_topic(topic_text)

        return HALForm(initial=data)

    def get_bound_form(self, data):
        return HALForm(data)

    def create_zip(self, pdf, metadata):
        s = BytesIO()
        with ZipFile(s, 'w') as zipFile:
            zipFile.writestr("article.pdf", str(pdf))
            zipFile.writestr("meta.xml", str(metadata))

        with open('/tmp/hal.zip', 'wb') as f:
            with ZipFile(f, 'w') as zipFile:
                zipFile.writestr("article.pdf", str(pdf))
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
            metadata = self.createMetadata(form)

            # Bundling the metadata and the PDF
            self.log("### Creating ZIP file")
            zipFile = self.create_zip(pdf, metadata)

            # Creating a new deposition
            self.log("### Creating a new deposition")

            host = 'api-preprod.archives-ouvertes.fr'
            conn = http_client.HTTPConnection(host)
            conn.putrequest('POST', '/sword/hal', True, True)
            zipContent = zipFile.getvalue()
            headers = {
                'Authorization': self.encodeUserData(),
                'Host': host,
                'X-Packaging': 'http://purl.org/net/sword-types/AOfr',
                'Content-Type': 'application/zip',
                'Content-Disposition': 'attachment; filename=meta.xml',
                'Content-Length': len(zipContent),
                }
            for header, value in headers.items():
                conn.putheader(header, value)
            conn.endheaders()
            conn.send(zipContent)
            resp = conn.getresponse()

            xml_response = resp.read()
            conn.close()

            parser = etree.XMLParser(encoding='utf-8')
            receipt = etree.parse(BytesIO(xml_response), parser)
            receipt = receipt.getroot()
            deposition_id = receipt.find('{http://www.w3.org/2005/Atom}id').text
            # TODO store the password for the paper:
            # can be used later by the user to modify the upload
            # password = receipt.find(
            #    '{http://hal.archives-ouvertes.fr/}password').text
            document_url = resp.getheader('location')

            if not deposition_id:
                raise DepositError(__('HAL rejected the submission'))

            self.log("Deposition id: %s" % deposition_id)

            deposit_result.identifier = deposition_id
            deposit_result.splash_url = document_url
            deposit_result.pdf_url = deposit_result.splash_url + '/document'

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
                deposit_result.status = 'DRY_SUCCESS'

        except DepositError as e:
            raise e
        except Exception as e:
            self.log("Caught exception:")
            self.log(str(type(e))+': '+str(e)+'')
            self.log(traceback.format_exc())
            raise DepositError(
                'Connection to HAL failed. Please try again later.')

        return deposit_result

    def createMetadata(self, form):
        formatter = AOFRFormatter()
        metadata = formatter.toString(self.paper, 'article.pdf',
                                      form, pretty=True)
        return metadata

protocol_registry.register(HALProtocol)
