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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
# USA.
#



import json

import requests

from django.utils.translation import ugettext as _

from deposit.protocol import DepositError
from deposit.protocol import DepositResult
from deposit.protocol import RepositoryProtocol
from deposit.registry import protocol_registry
from deposit.zenodo.forms import ZenodoForm
from papers.utils import kill_html
from papers.utils import extract_domain



class ZenodoProtocol(RepositoryProtocol):
    """
    A protocol to submit using the Zenodo API
    """

    hiccups_message = _('This happens when Zenodo has hiccups. Please try again in a few minutes or use a different repository in the above menu')
    form_class = ZenodoForm
    # How long do we wait for responses from Zenodo?
    timeout =16


    def __str__(self):
        return "Zenodo Protocol"


    def _error_msg(self, msg):
        """
        Appends the hiccup with a whitespace to the error message
        :param msg: Message as string
        :return: Message + hicchup message as string
        """
        return "{} {}".format(msg, self.hiccups_message)

    def _create_empty_publication(self):
        """
        Creates an empty upload. If this does not succeed, raises DepositError
        :returns: zenodo id
        """
        headers = {
            'Content-Type' : 'application/json',
        }
        params = {
            'access_token' : self.repository.api_key
        }
        r = requests.post(
            self.repository.endpoint,
            params=params,
            headers=headers,
            timeout=self.timeout,
            json={},
        )
        self.log_request(r, 201,self._error_msg(_('Unable to create new deposition on Zenodo.')))

        return r.json().get('id')

    def init_deposit(self, paper, user):
        """
        Refuse deposit when the paper is already on Zenodo
        """
        super(ZenodoProtocol, self).init_deposit(paper, user)
        for r in paper.oairecords:
            domain = extract_domain(r.splash_url) or ''
            if domain.endswith('zenodo.org'):
                return False
        return True

    def get_form_initial_data(self, **kwargs):
        data = super(ZenodoProtocol, self).get_form_initial_data(**kwargs)
        if self.paper.abstract:
            data['abstract'] = kill_html(self.paper.abstract)
        else:
            self.paper.consolidate_metadata(wait=False)
        return data

    def _get_metadata(self, form):
        """
        We use the cached property metadata and fill some more information from the form.
        Metadata is created in the order of zenodo documentation.
        """
        metadata = dict()
        pub_type = convert_doctype(self.metadata.doctype)
        metadata['upload_type'] = pub_type[0]
        if len(pub_type) == 2:
            metadata['publication_type'] = pub_type[1]
        metadata['publication_date'] = self.metadata.pubdate.isoformat()
        metadata['title'] = self.metadata.get('title')
        def format_creator(author):
            creator = {
                'name' : '{}, {}'.format(author.get('last'), author.get('first')),
            }
            if author.get('orcid'):
                creator['orcid'] = author.get('orcid')
            return creator
        metadata['creators'] = list(map(format_creator, self.metadata.authors))
        metadata['description'] = form.cleaned_data['abstract'] or kill_html(self.paper.abstract)
        metadata['access_right'] = 'open'
        metadata['license'] = form.cleaned_data['license'].transmit_id
        # Here we have a list with a mapping. If there's a value, we set it, otherwise not
        l = [
            ('doi', 'doi'),
            ('journal', 'journal_title'),
            ('volume', 'journal_volume'),
            ('issue', 'journal_issue'),
            ('pages', 'journal_pages')
        ]
        for i in l:
            source_key = i[0]
            target_key = i[1]
            if self.metadata.get(source_key):
                metadata[target_key] = self.metadata.get(source_key)

        data = {
            'metadata' : metadata,
        }

        return data

    def log_request(self, r, expected_status_code, error_msg):
        """
        Logs an HTTP request and raises an error if the status code is
        unexpected.
        """
        # Call the generic log_request handler to check if there is any error
        super_exc = None
        try:
            super(ZenodoProtocol, self).log_request(
                r, expected_status_code, error_msg
            )
        except DepositError as exc:
            super_exc = exc

        # No error (request went as expected), we can just return
        if super_exc is None:
            return

        # If there was an error, do the Zenodo-specific error handling here.
        try:
            error = r.json()
            # Check for validation errors because the DOI already exists
            if (
                    r.status_code == 400
                    and 'Validation error' in error.get('message')
                    and any([
                        'DOI already exists' in item.get('message')
                        for item in error.get('errors', [])
                    ])
            ):
                raise DepositError(_(
                    'This document is already in Zenodo. '
                    'Zenodo refused the deposit.'
                ))
        except Exception as exc:
            if isinstance(exc, DepositError):
                # Any DepositError is simply kept as is
                raise exc
            else:
                # There was an error within error handling code, just return
                # the super exception
                raise super_exc
        # We some other error, raise that
        raise super_exc

    def submit_deposit(self, pdf, form):
        if self.repository.api_key is None:
            raise DepositError(_("No Zenodo API key provided."))

        deposit_result = DepositResult()
        # Set the license for the deposit result if delivered
        deposit_result = self._add_license_to_deposit_result(deposit_result, form)

        # Create empty publication
        self.log('### Creating new emtpy publication')
        deposit_result.identifier = self._create_empty_publication()
        self.log("Deposition id: %d" % deposit_result.identifier)

        # Upload the file
        self._upload_pdf(pdf, deposit_result.identifier)

        # Generating the metadata
        self.log("### Generating the metadata")
        metadata = self._get_metadata(form)

        self.log('Metadata looks like:')
        self.log(json.dumps(metadata, indent=4))

        # Submitting the metadata
        self.log("### Submitting the metadata")
        self._submit_metadata(deposit_result.identifier, metadata)

        self.log("### Publishing the deposition")
        publish_response = self._publish(deposit_result.identifier)

        self.log('### Finish DepositResult')
        deposit_result.splash_url = publish_response.get('links').get('html')
        deposit_result.pdf_url = publish_response.get('files')[0].get('links').get('self')

        return deposit_result

    def _submit_metadata(self, zenodo_id, metadata):
        """
        Adds the metadata to a deposition on Zenodo.
        :param zenodo_id: Zenodo id
        :param metadata: metadata, serializable as json
        """
        params = {
            'access_token' : self.repository.api_key
        }
        headers = {
            'Content-Type' : 'application/json',
        }
        r = requests.put(
            self.repository.endpoint + '/{}'.format(zenodo_id),
            params=params,
            headers=headers,
            timeout=self.timeout,
            data=json.dumps(metadata),
        )
        self.log_request(r, 200, self._error_msg(_('Unable to submit paper metadata to Zenodo')))

    def _publish(self, zenodo_id):
        """
        Publishes a deposition
        :param zenodo_id: Zenodo id
        """
        params = {
            'access_token' : self.repository.api_key
        }
        r = requests.post(
            self.repository.endpoint + '/{}/actions/publish'.format(zenodo_id),
            params=params,
            timeout=self.timeout,
        )
        self.log_request(r, 202, _('Unable to publish the deposition on Zenodo'))
        self.log(r.text)
        return r.json()

    def _upload_pdf(self, pdf, zenodo_id):
        """
        Uploads the pdf to the given zenodo_id
        :param zenodo_id: Id of zenodo deposition
        """
        self.log('### Uploading PDF ###')
        params = {
            'access_token' : self.repository.api_key
        }
        data = {
            'name' : '{}.pdf'.format(self.paper.slug),
        }
        files = {
            'file' : open(pdf, 'rb'),
        }
        r = requests.post(
            self.repository.endpoint + '/{}/files'.format(zenodo_id),
            params=params,
            data=data,
            files=files,
        )
        self.log_request(r, 201, self._error_msg(_('Unable to transfer the document to Zenodo')))


protocol_registry.register(ZenodoProtocol)


def convert_doctype(doctype):
    tr = {
        'journal-article': ('publication', 'article'),
        'proceedings-article': ('publication', 'conferencepaper'),
        'book-chapter': ('publication', 'section'),
        'book': ('publication', 'book'),
        'journal-issue': ('publication', 'book'),
        'proceedings': ('publication', 'book'),
        'reference-entry': ('publication', 'other'),
        'poster': ('poster',),
        'report': ('publication', 'report'),
        'thesis': ('publication', 'thesis'),
        'dataset': ('dataset',),
        'preprint': ('publication', 'preprint'),
        'other': ('publication', 'other'),
    }
    return tr[doctype]
