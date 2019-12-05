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



from io import BytesIO

import os
import requests
from requests.packages.urllib3.exceptions import HTTPError
from requests.packages.urllib3.exceptions import ReadTimeoutError

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.core.files.base import ContentFile
from django.http import FileResponse
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext as _
from django.views.decorators.http import require_POST
from django.views.generic import View
from jsonview.decorators import json_view
from papers.user import is_authenticated
import PyPDF2
from PyPDF2.utils import PyPdfError
from upload.forms import AjaxUploadForm
from upload.forms import UrlDownloadForm
from upload.models import MAX_ORIG_NAME_LENGTH
from upload.models import THUMBNAIL_MAX_WIDTH
from upload.models import UploadedPDF
from ratelimit.decorators import ratelimit
import wand.exceptions
import wand.image


# AJAX upload


@json_view
@require_POST
@user_passes_test(is_authenticated)
@ratelimit(key='ip', rate='300/d')
def handleAjaxUpload(request):
    form = AjaxUploadForm(request.POST, request.FILES)
    if form.is_valid():
        # We read the whole file in memory, which
        # is reasonably safe because we know it's not too big
        pdf_file = request.FILES['upl'].read()
        orig_name = request.FILES['upl'].name

        status = save_pdf(request.user, orig_name, pdf_file)

        if status['status'] == 'error':
            status['upl'] = status['message']
            return status, 403

        return status
    else:
        return form.errors, 403


def make_thumbnail(pdf_blob):
    """
    Takes a PDF file (represented as a string) and returns a pair:
    - the number of pages
    - a thumbnail of its first page in PNG (as a string again),
    or None if anything failed.
    """
    try:
        resolution = int(THUMBNAIL_MAX_WIDTH / (21/2.54))+1
        num_pages = None

        try:  # We try to extract the first page of the PDF
            orig_pdf = BytesIO(pdf_blob)
            reader = PyPDF2.PdfFileReader(orig_pdf)
            num_pages = reader.getNumPages()
            if not reader.isEncrypted and num_pages == 0:
                return
            writer = PyPDF2.PdfFileWriter()
            writer.addPage(reader.getPage(0))
            first_page = BytesIO()
            writer.write(first_page)
        except PyPdfError:
            # PyPDF2 failed (maybe it believes the file is encrypted…)
            # We try to convert the file with ImageMagick (wand) anyway,
            # rendering the whole PDF as we have not been able to
            # select the first page
            pass

        # We render the PDF
        with wand.image.Image(blob=pdf_blob, format='pdf', resolution=resolution) as image:
            if image.height == 0 or image.width == 0:
                return
            if num_pages is None:
                num_pages = len(image.sequence)
            if num_pages == 0:
                return
            image = wand.image.Image(image=image.sequence[0])

            image.format = 'png'
            return (num_pages, image.make_blob())
    except wand.exceptions.WandException:
        # Wand failed: we consider the PDF file as invalid
        pass
    except ValueError:
        pass


def save_pdf(user, orig_name, pdf_blob):
    """
    Given a User and a PDF file represented as a stream,
    create the UploadedPDF object.

    :returns: the status context telling whether the operation has succeded.
    """

    response = {'status': 'error'}
    # Check that the file is a valid PDF by extracting the first page
    res = make_thumbnail(pdf_blob)
    if res is None:
        response['message'] = _('Invalid PDF file.')
        return response

    num_pages, png_blob = res

    # Otherwise we save the file!
    upload = UploadedPDF(
            user=user,
            num_pages=num_pages,
            orig_name=orig_name[:MAX_ORIG_NAME_LENGTH])
    f = ContentFile(pdf_blob)
    thumbnail_file = ContentFile(png_blob)
    upload.file.save('document.pdf', f)
    upload.thumbnail.save('thumbnail.png', thumbnail_file)
    upload.save()

    response = {
            'status': 'success',
            'size': len(pdf_blob),
            'num_pages': num_pages,
            'thumbnail': upload.thumbnail.url,
            'file_id': upload.id,
            }
    return response


@json_view
@require_POST
@user_passes_test(is_authenticated)
@ratelimit(key='ip', rate='300/d')
def handleUrlDownload(request):
    response = {'status': 'error'}
    form = UrlDownloadForm(request.POST)
    if not form.is_valid():
        response['message'] = _('Invalid form.')
        return response, 403
    content = None
    try:
        r = requests.get(form.cleaned_data[
                         'url'], timeout=settings.URL_DEPOSIT_DOWNLOAD_TIMEOUT, stream=True)
        r.raise_for_status()
        content = r.raw.read(settings.DEPOSIT_MAX_FILE_SIZE+1, decode_content=False)

        if len(content) > settings.DEPOSIT_MAX_FILE_SIZE:
            response['message'] = _('File too large.')

        content_type = r.headers.get('content-type')
        if 'text/html' in content_type:
            response['message'] = (  # Left as one line for compatibility purposes
                _('Invalid content type: this link points to a web page, we need a direct link to a PDF file.'))

    except requests.exceptions.SSLError:
        response['message'] = _('Invalid SSL certificate on the remote server.')
    except requests.exceptions.Timeout:
        response['message'] = _('Invalid URL (server timed out).')
    except requests.exceptions.RequestException:
        response['message'] = _('Invalid URL.')
    except ReadTimeoutError:
        response['message'] = _('Invalid URL (server timed out).')
    except HTTPError:
        response['message'] = _('Invalid URL.')

    if 'message' in response:
        return response, 403

    orig_name = form.cleaned_data['url']

    response = save_pdf(request.user, orig_name, content)

    if response['status'] == 'error':
        return response, 403

    return response

class FileDownloadView(View):
    """
    View to get an uploaded file
    """

    def get(self, request, pk, token):
        """
        :param pk: Primary key of object
        :param token: Token that must coincident with objects token
        :returns: HttpResponse
        """
        pdf = get_object_or_404(UploadedPDF.objects, pk=pk)

        if pdf.token != token:
            return HttpResponseForbidden(_("Access to this resource not permitted"))
        
        path = os.path.join(settings.MEDIA_ROOT, pdf.file.name)

        return FileResponse(open(path, 'rb'), as_attachment=True)
