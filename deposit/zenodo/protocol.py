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

    form_class = ZenodoForm

    def __init__(self, repository, **kwargs):
        super(ZenodoProtocol, self).__init__(repository, **kwargs)
        # We let the interface define another API endpoint (sandbox…)
        self.api_url = repository.endpoint
        if not self.api_url:
            self.api_url = "https://zenodo.org/api/deposit/depositions"

    def __str__(self):
        return "Zenodo Protocol"

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

    def submit_deposit(self, pdf, form, dry_run=False):
        if self.repository.api_key is None:
            raise DepositError(_("No Zenodo API key provided."))
        api_key = self.repository.api_key
        api_url_with_key = self.api_url+'?access_token='+api_key

        deposit_result = DepositResult()
        # Set the license for the deposit result if delivered
        deposit_result = self._add_license_to_deposit_result(deposit_result, form)

        # Checking the access token
        self.log("### Checking the access token")
        r = requests.get(api_url_with_key)
        hiccups_message = ' ' + _(
            'This happens when Zenodo has hiccups. '
            'Please try again in a few minutes or use a different '
            'repository in the menu above.'
        )
        self.log_request(
            r, 200,
            _('Unable to authenticate to Zenodo.') + hiccups_message
        )

        # Creating a new deposition
        self.log("### Creating a new deposition")
        headers = {"Content-Type": "application/json"}
        r = requests.post(api_url_with_key, data=str("{}"), headers=headers)
        self.log_request(r, 201, _(
            'Unable to create a new deposition on Zenodo.')+hiccups_message)
        deposition_id = r.json()['id']
        deposit_result.identifier = deposition_id
        self.log("Deposition id: %d" % deposition_id)

        # Uploading the PDF
        self.log("### Uploading the PDF")
        data = {'name': 'article.pdf'}
        files = {'file': open(pdf.absolute_path, 'rb')}
        r = requests.post(
            (
                self.api_url + "/%s/files?access_token=%s" %
                (deposition_id, api_key)
            ),
            data=data, files=files
        )
        self.log_request(r, 201, _(
            'Unable to transfer the document to Zenodo.')+hiccups_message)

        # Creating the metadata
        self.log("### Generating the metadata")
        data = self.createMetadata(form)
        self.log(json.dumps(data, indent=4)+'')

        # Check that there is an abstract
        if data['metadata'].get('description', '') == '':
            self.log('No abstract found, aborting.')
            raise DepositError(_(
                'No abstract is available for this paper but Zenodo '
                'requires one. Please provide it using the metadata panel.'
            ))

        # Submitting the metadata
        self.log("### Submitting the metadata")
        r = requests.put(
            self.api_url + "/%s?access_token=%s" % (deposition_id, api_key),
            data=json.dumps(data),
            headers=headers
        )
        self.log_request(r, 200, _(
            'Unable to submit paper metadata to Zenodo.'))

        if dry_run:
            # Deleting the deposition
            self.log("### Deleting the deposition")
            r = requests.delete(self.api_url+"/%s?access_token=%s" %
                                (deposition_id, api_key))
            self.log(r.text)
            deposit_result.status = 'faked'
            deposit_result.splash_url = 'http://sandbox.zenodo.org/fake'
            deposit_result.pdf_url = deposit_result.splash_url
        else:
            self.log("### Publishing the deposition")
            r = requests.post(
                self.api_url + "/%s/actions/publish?access_token=%s" %
                (deposition_id, api_key)
            )
            self.log_request(r, 202, _(
                'Unable to publish the deposition on Zenodo.'))
            self.log(r.text)

            deposition_object = r.json()
            links = deposition_object.get('links', {})
            deposit_result.splash_url = links.get(
                'record_html', 'https://zenodo.org/'
            )
            deposit_result.pdf_url = (
                deposit_result.splash_url + '/files/article.pdf'
            )

        return deposit_result

    def createMetadata(self, form):
        metadata = {}
        oairecords = self.paper.sorted_oai_records
        publications = self.paper.publications

        # Document type
        dt = swordDocumentType(self.paper)
        metadata['upload_type'] = dt[0]
        if dt[0] == 'publication':
            metadata['publication_type'] = dt[1]

        # Publication date
        metadata['publication_date'] = self.paper.pubdate.isoformat()

        # Title
        metadata['title'] = self.paper.title

        # Creators
        def formatAuthor(author):
            res = {'name': author.name.last+', '+author.name.first}
            if author.researcher and author.researcher.orcid:
                res['orcid'] = author.researcher.orcid
            # TODO: affiliation
            return res
        metadata['creators'] = list(map(formatAuthor, self.paper.authors))

        # Abstract
        abstract = form.cleaned_data[
            'abstract'] or kill_html(self.paper.abstract)

        metadata['description'] = abstract

        # Access right: TODO

        # License
        metadata['license'] = form.cleaned_data['license'].transmit_id

        # Embargo date: TODO

        # DOI
        for publi in publications:
            metadata['doi'] = publi.doi
            if publi.pubdate:
                metadata['publication_date'] = publi.pubdate.isoformat()
                if publi.journal:
                    metadata['journal_title'] = publi.journal.title
                else:
                    metadata['journal_title'] = publi.journal_title
                if publi.volume:
                    metadata['journal_volume'] = publi.volume
                if publi.issue:
                    metadata['journal_issue'] = publi.issue
                if publi.pages:
                    metadata['journal_pages'] = publi.pages
                if publi.container:
                    metadata['conference_title'] = publi.container
                break

        # Related identifiers
        idents = [{
                'relation': 'isAlternateIdentifier',
                'identifier': r.splash_url
            } for r in oairecords]
        for publi in publications:
            if publi.journal and publi.journal.issn:
                idents.append(
                    {'relation': 'isPartOf', 'identifier': publi.journal.issn})

        data = {"metadata": metadata}
        return data


protocol_registry.register(ZenodoProtocol)


def swordDocumentType(paper):
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
    return tr[paper.doctype]
