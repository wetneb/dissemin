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
from statistics.models import COMBINED_STATUS_CHOICES
from statistics.models import BareAccessStatistics

from allauth.socialaccount.signals import post_social_login
from deposit.models import DepositRecord
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseForbidden
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.template import loader
from django.utils.encoding import escape_uri_path
from django.utils.translation import ugettext as _
from django.utils.translation import ungettext
from django.views import generic
from haystack.generic_views import SearchView
from notification.api import get_notifications
from papers.doi import to_doi
from papers.errors import MetadataSourceException
from papers.forms import PaperForm
from papers.forms import FrontPageSearchForm
from papers.models import Department
from papers.models import Institution
from papers.models import Paper
from papers.models import Researcher
from papers.user import is_admin
from papers.user import is_authenticated
from papers.utils import validate_orcid
from publishers.models import Journal
from publishers.models import Publisher
from publishers.views import SlugDetailView
from search import SearchQuerySet


def fetch_on_orcid_login(sender, **kwargs):
    account = kwargs['sociallogin'].account

    # Only prefetch if the social login refers to a valid ORCID account
    orcid = validate_orcid(account.uid)
    if not orcid:
        return

    profile = account.extra_data
    user = None
    if '_user_cache' in account.__dict__:
        user = account.user
    r = Researcher.get_or_create_by_orcid(orcid, profile, user)

    if not r: # invalid ORCID profile (e.g. no name provided)
        return

    if r.user_id is None and user is not None:
        r.user = user
        r.save(update_fields=['user'])
    if r.empty_orcid_profile is None:
        r.init_from_orcid()
    else:
        r.fetch_everything_if_outdated()

post_social_login.connect(fetch_on_orcid_login)

# Number of papers shown on a search results page
NB_RESULTS_PER_PAGE = 20


def index(request):
    """
    View for the home page
    """
    context = {
        'search_form': FrontPageSearchForm(),
        'combined_status':
            [{'choice_value': v, 'choice_label': l}
             for v, l in COMBINED_STATUS_CHOICES]
        }
    return render(request, 'papers/index.html', context)


class PaperSearchView(SearchView):
    """Displays a list of papers and a search form."""

    paginate_by = NB_RESULTS_PER_PAGE
    template_name = 'papers/search.html'
    form_class = PaperForm
    queryset = SearchQuerySet().models(Paper)

    def get(self, request, *args, **kwargs):
        if not is_admin(request.user):
            request.GET = request.GET.copy()
            request.GET.pop('visible', None)
            request.GET.pop('availability', None)
            request.GET.pop('oa_status', None)
        return super(PaperSearchView, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(PaperSearchView, self).get_context_data(**kwargs)
        search_description = _('Papers')
        query_string = self.request.META.get('QUERY_STRING', '')
        context['breadcrumbs'] = [(search_description, '')]
        context['search_description'] = (
            search_description if query_string else _('All papers'))
        context['head_search_description'] = _('Papers')
        nb_results = self.queryset.count()
        context['nb_results'] = ungettext(
            '%d paper found',
            '%d papers found',
            nb_results) % nb_results
        context['search_stats'] = BareAccessStatistics.from_search_queryset(self.queryset)
        context['on_statuses'] = json.dumps(context['form'].on_statuses())
        context['ajax_url'] = self.request.path

        # Notifications
        # TODO: unefficient query.
        notifications = get_notifications(self.request)
        selected_messages = map(
            lambda n: n.serialize_to_json(),
            sorted(notifications, key=lambda msg: msg.level)[:3])
        context['messages'] = selected_messages

        return context

    def get_form_kwargs(self):
        """
        We make sure the search is valid even if no parameter
        was passed, in which case we add a default empty query.
        Otherwise the search form is not bound and search fails.
        """
        args = super(PaperSearchView, self).get_form_kwargs()

        if 'data' not in args:
            args['data'] = {self.search_field:''}
        return args

    def render_to_response(self, context, **kwargs):
        if self.request.META.get('CONTENT_TYPE') == 'application/json':
            response = self.raw_response(context, **kwargs)
            return HttpResponse(json.dumps(response),
                                content_type='application/json')
        return super(PaperSearchView, self)\
            .render_to_response(context, **kwargs)

    def raw_response(self, context, **kwargs):
        context['request'] = self.request
        listPapers = loader.render_to_string('papers/paperList.html', context)
        stats = context['search_stats'].pie_data()
        stats['on_statuses'] = context['form'].on_statuses()
        return {
            'listPapers': listPapers,
            'messages': context['messages'],
            'stats': stats,
            'nb_results': context['nb_results'],
        }

    def url_with_query_string(self, url=None, query_string=None):
        """
        Returns the current URL with its query string.

        Both the URL and the query string can be overriden.
        """
        url = url or escape_uri_path(self.request.path)
        if query_string is None:
            query_string = self.request.META.get('QUERY_STRING', '')
        if query_string:
            url += '?' + query_string
        return url


class ResearcherView(PaperSearchView):
    """
    Displays the papers of a given researcher.
    """

    def get(self, request, *args, **kwargs):
        if 'researcher' in kwargs:
            researcher = get_object_or_404(Researcher, pk=kwargs['researcher'])
        elif 'orcid' in kwargs:
            try:
                researcher = Researcher.objects.get(orcid=kwargs['orcid'])
            except Researcher.DoesNotExist:
                try:
                    orcid = validate_orcid(kwargs['orcid'])
                    researcher = Researcher.get_or_create_by_orcid(orcid)
                    if not researcher:
                        raise Http404(_("""
                            Invalid ORCID profile.
                            Please make sure it includes a public name.
                            """))
                    researcher.init_from_orcid()
                except MetadataSourceException:
                    raise Http404(_('Invalid ORCID profile.'))

        if kwargs.get('slug') != researcher.slug:
            view_args = {'researcher': researcher.id, 'slug': researcher.slug}
            url = reverse('researcher', kwargs=view_args)
            self.url = self.url_with_query_string(url=url)
            return HttpResponsePermanentRedirect(self.url)

        self.queryset = self.queryset.filter(researchers=researcher.id)
        self.researcher = researcher
        return super(ResearcherView, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(ResearcherView, self).get_context_data(**kwargs)
        researcher = self.researcher
        # researcher corresponding to the currently logged in user
        try:
            context['user_researcher'] = Researcher.objects.get(user=self.request.user)
        except (Researcher.DoesNotExist, TypeError):
            pass # no logged in user
        context['researcher'] = researcher
        context['researcher_id'] = researcher.id
        context['search_description'] += _(' authored by ')+unicode(researcher)
        context['head_search_description'] = unicode(researcher)
        context['breadcrumbs'] = researcher.breadcrumbs()
        return context

    def raw_response(self, context, **kwargs):
        response = super(ResearcherView, self).raw_response(context, **kwargs)
        researcher = self.researcher
        if researcher.current_task:
            response['status'] = researcher.current_task
            response['display'] = researcher.get_current_task_display()
        return response


class DepartmentPapersView(PaperSearchView):
    """
    Displays the papers of researchers from a given department in an
    institution.
    """

    def get(self, request, *args, **kwargs):
        self.dept = get_object_or_404(Department, pk=kwargs.get('pk'))
        self.queryset = self.queryset.filter(departments=self.dept.id)
        return super(DepartmentPapersView, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(DepartmentPapersView, self).get_context_data(**kwargs)
        context['department'] = self.dept
        context['search_description'] = context['head_search_description'] = (
            unicode(self.dept))
        context['breadcrumbs'] = self.dept.breadcrumbs()+[(_('Papers'), '')]
        return context


class PublisherPapersView(PaperSearchView):
    """
    Displays the papers of a given publisher.

    :class:`PublisherPapersView` is subclassed by :class:`JournalPapersView`,
    which simply overrides a couple of variables.
    """

    publisher_key = 'publisher'
    publisher_cls = Publisher
    published_by = _(' published by ')

    def get(self, request, *args, **kwargs):
        if not is_admin(request.user):
            raise Http404()
        publisher = get_object_or_404(
            self.publisher_cls, pk=kwargs[self.publisher_key])
        self.publisher = publisher
        self.queryset = self.queryset.filter(
            **{self.publisher_key: publisher.id})
        return super(PublisherPapersView, self)\
            .get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        publisher = self.publisher
        context = super(PublisherPapersView, self)\
            .get_context_data(**kwargs)
        context[self.publisher_key] = publisher
        context['search_description'] += self.published_by+unicode(publisher)
        context['head_search_description'] = unicode(publisher)
        context['breadcrumbs'] = publisher.breadcrumbs()+[(_('Papers'), '')]
        return context


class JournalPapersView(PublisherPapersView):
    """Displays the papers in a given journal."""

    publisher_key = 'journal'
    publisher_cls = Journal
    published_by = _(' in ')

# TODO: this should be moved to /ajax/


@user_passes_test(is_authenticated)
def refetchResearcher(request, pk):
    researcher = get_object_or_404(Researcher, pk=pk)
    if researcher.user != request.user and not request.user.is_staff:
        return HttpResponseForbidden("Not authorized to update papers for this researcher.")
    from backend.tasks import fetch_everything_for_researcher
    fetch_everything_for_researcher.delay(pk=pk)
    return redirect(request.META['HTTP_REFERER'])


@user_passes_test(is_authenticated)
def myProfileView(request):
    try:
        r = Researcher.objects.get(user=request.user)
        return ResearcherView.as_view()(request,
                                        researcher=r.pk,
                                        slug=r.slug)
    except Researcher.DoesNotExist:
        return render(request, 'papers/createProfile.html')


class DepartmentView(generic.DetailView):
    model = Department
    template_name = 'papers/department.html'

    def get_context_data(self, **kwargs):
        context = super(DepartmentView, self).get_context_data(**kwargs)
        context['breadcrumbs'] = self.object.breadcrumbs()
        return context


class InstitutionView(SlugDetailView):
    model = Institution
    template_name = 'papers/institution.html'
    view_name = 'institution'

    def get_context_data(self, **kwargs):
        context = super(InstitutionView, self).get_context_data(**kwargs)
        context['breadcrumbs'] = self.object.breadcrumbs()
        return context


class PaperView(SlugDetailView):
    model = Paper
    template_name = 'papers/paper.html'
    view_name = 'paper'

    def departments(self):
        paper = self.object
        return Department.objects.filter(researcher__author__paper=paper).distinct()

    def get_object(self):
        queryset = self.get_queryset()
        pk = self.kwargs.get('pk', None)
        doi = self.kwargs.get('doi', None)
        if doi:
            doi = to_doi(doi)

        paper = None
        try:
            if pk is not None:
                paper = queryset.get(pk=pk)
            elif doi is not None:
                paper = Paper.get_by_doi(doi)
            else:
                raise AttributeError("Paper view expects a DOI or a pk")
        except ObjectDoesNotExist:
            pass

        if not paper:
            paper = Paper.create_by_doi(doi)
            if paper is None or paper.is_orphan():
                raise Http404(_("No %(verbose_name)s found matching the query") %
                              {'verbose_name': Paper._meta.verbose_name})
        return paper

    def get_context_data(self, **kwargs):
        context = super(PaperView, self).get_context_data(**kwargs)
        context['breadcrumbs'] = self.object.breadcrumbs()
        if 'deposit' in self.request.GET:
            try:
                pk = int(self.request.GET['deposit'])
                dep = DepositRecord.objects.get(pk=pk)
                if dep.paper_id == self.object.id:
                    context['deposit'] = dep
            except (TypeError, ValueError, DepositRecord.DoesNotExist):
                pass
        context['can_be_deposited'] = (not self.request.user.is_authenticated
                    or self.object.can_be_deposited(self.request.user))

        # Pending deposits
        context['pending_deposits'] = self.object.depositrecord_set.filter(
            status='pending')

        return context

    def redirect(self, **kwargs):
        if 'pk' not in kwargs:
            del kwargs['doi']
            kwargs['pk'] = self.object.pk
        return super(PaperView, self).redirect(**kwargs)

class InstitutionsMapView(generic.base.TemplateView):
    template_name = 'papers/institutions.html'

