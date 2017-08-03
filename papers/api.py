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

import json

from django.conf.urls import url
from django.http import Http404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from jsonview.decorators import json_view
from jsonview.exceptions import BadRequest
from papers.baremodels import BareName
from papers.baremodels import BarePaper
from papers.errors import MetadataSourceException
from papers.models import Paper
from papers.name import parse_comma_name
from papers.utils import tolerant_datestamp_to_datetime
from papers.views import PaperSearchView


@json_view
def api_paper_doi(request, doi):
    p = Paper.get_by_doi(doi)
    if p is None:
        raise Http404("The paper you requested could not be found.")
    return {
            'status': 'ok',
            'paper': p.json()
            }


class PaperSearchAPI(PaperSearchView):
    @json_view
    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super(PaperSearchAPI, self).dispatch(*args, **kwargs)

    def render_to_response(self, context, **kwargs):
        stats = context['search_stats'].pie_data()
        papers = [
            result.object.json()
            for result in context['object_list']
            ]
        response = {
            'messages': context['messages'],
            'stats': stats,
            'nb_results': context['nb_results'],
            'papers': papers,
        }
        return response

@json_view
@csrf_exempt
@require_POST
def api_paper_query(request):
    try:
        fields = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise BadRequest('Invalid JSON payload')

    doi = fields.get('doi')
    if doi:
        p = None
        try:
            p = Paper.create_by_doi(doi, bare=True)
        except MetadataSourceException:
            pass
        if p is None:
            raise BadRequest('Could not find a paper with this DOI')
        return {'status': 'ok', 'paper': p.json()}

    title = fields.get('title')
    if type(title) != unicode or not title or len(title) > 512:
        raise BadRequest(
            'Invalid title, has to be a non-empty string shorter than 512 characters')

    date = fields.get('date')
    if type(date) != unicode:
        raise BadRequest('A date is required')
    try:
        date = tolerant_datestamp_to_datetime(date)
    except ValueError as e:
        raise BadRequest(unicode(e))

    authors = fields.get('authors')
    if type(authors) != list:
        raise BadRequest('A list of authors is expected')

    parsed_authors = []
    for a in authors:
        author = None
        if not isinstance(a, dict):
            raise BadRequest('Invalid author')

        if 'first' in a and 'last' in a:
            if type(a['first']) != unicode or type(a['last']) != unicode or not a['last']:
                raise BadRequest('Invalid (first,last) name provided')
            else:
                author = (a['first'], a['last'])
        elif 'plain' in a:
            if type(a['plain']) != unicode or not a['plain']:
                raise BadRequest('Invalid plain name provided')
            else:
                author = parse_comma_name(a['plain'])

        if author is None:
            raise BadRequest('Invalid author')

        parsed_authors.append(BareName.create(author[0], author[1]))

    if not authors:
        raise BadRequest('No authors provided')

    try:
        p = BarePaper.create(title, parsed_authors, date)
    except ValueError:
        raise BadRequest('Invalid paper')

    return {'status': 'ok', 'paper': p.json()}


urlpatterns = [
    url(r'^(?P<doi>10\..*)$', api_paper_doi, name='api-paper-doi'),
    url(r'^query/?$', api_paper_query, name='api-paper-query'),
    url(r'^search/?$', PaperSearchAPI.as_view(), name='api-paper-search'),
]
