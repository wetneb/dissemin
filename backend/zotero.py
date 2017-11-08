# -*- encoding: utf-8 -*-
from __future__ import unicode_literals

from dissemin.settings import DOI_PROXY_DOMAIN

import requests

##### Zotero interface #####

def fetch_zotero_by_DOI(doi):
    """
    Fetch Zotero metadata for a given DOI.
    Works only with the doi_cache proxy.
    """
    try:
        request = requests.get('http://'+DOI_PROXY_DOMAIN+'/zotero/'+doi)
        return request.json()
    except ValueError as e:
        raise MetadataSourceException('Error while fetching Zotero metadata:\nInvalid JSON response.\n' +
                                      'Error: '+str(e))


def consolidate_publication(publi):
    """
    Fetches the abstract from Zotero and adds it to the publication if it succeeds.
    """
    zotero = fetch_zotero_by_DOI(publi.doi)
    if zotero is None:
        return publi
    for item in zotero:
        if 'abstractNote' in item:
            publi.description = sanitize_html(item['abstractNote'])
            publi.save(update_fields=['description'])
        for attachment in item.get('attachments', []):
            if attachment.get('mimeType') == 'application/pdf':
                publi.pdf_url = attachment.get('url')
                publi.save(update_fields=['pdf_url'])
                publi.about.update_availability()
    return publi
