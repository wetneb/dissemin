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

"""
This module defines most of the models used in the platform.

* :class:`Paper` represents a (deduplicated) paper.
   The sources it has been discovered from are witnessed
   by two types of records:
    * :class:`OaiRecord` instances are created by OAI-PMH sources, or
      metadata sources not originally in OAI-PMH but wrapped in this format
      by proaixy. They indicate the availability of the paper in repositories.
      They link to an :class:`OaiSource` object that indicates what data source
      we have got this record from.
   Multiple :class:`OaiRecord` can (and typically are) associated
   with a paper, when the metadata they contain yield the same paper fingerprint.
   These records are stored inside the Paper object in a JSON field.

* :class:`Researcher` represents a researcher profile (a physical person).
   This person has a cannonical :class:`Name`, but can also be associated with
   other names through a :class:`NameVariant` relation (indicating a confidence value
   for the association of the name with this reseracher).

* Researchers can be organized into :class:`Department` instances, which belong to an
  :class:`Institution`.

"""

from __future__ import unicode_literals

from datetime import datetime
from datetime import timedelta
import re
import haystack
from statistics.models import AccessStatistics
from statistics.models import combined_status_for_instance
from statistics.models import STATUS_CHOICES_HELPTEXT

from caching.base import CachingManager
from caching.base import CachingMixin
from celery.result import AsyncResult
from dissemin.settings import POSSIBLE_LANGUAGE_CODES
from dissemin.settings import PROFILE_REFRESH_ON_LOGIN
from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField
from django.contrib.postgres.fields import ArrayField
from django_countries.fields import CountryField
from django_countries.fields import countries
from djgeojson.fields import PointField
from django.conf import settings
from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key
from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.db import DataError
from django.db import models
from django.template.defaultfilters import slugify
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from django.utils.http import urlencode
from papers.baremodels import BareAuthor
from papers.baremodels import BareName
from papers.baremodels import BareOaiRecord
from papers.baremodels import BarePaper
from papers.baremodels import MAX_NAME_LENGTH
from papers.baremodels import PAPER_TYPE_CHOICES
from papers.baremodels import PAPER_TYPE_PREFERENCE
from papers.doi import to_doi
from papers.errors import MetadataSourceException
from papers.name import name_similarity
from papers.name import match_names
from papers.name import unify_name_lists
from papers.orcid import OrcidProfile
from papers.utils import affiliation_is_greater
from papers.utils import validate_orcid
from papers.utils import iunaccent
from publishers.models import Journal
from publishers.models import Publisher
from solo.models import SingletonModel
from search import SearchQuerySet

UPLOAD_TYPE_CHOICES = [
   ('preprint', _('Preprint')),
   ('postprint', _('Postprint')),
   ('pdfversion', _("Published version")),
   ]

HARVESTER_TASK_CHOICES = [
   ('init', _('Preparing profile')),
   ('orcid', _('Fetching publications from ORCID')),
   ('crossref', _('Fetching publications from CrossRef')),
   ('base', _('Fetching publications from BASE')),
   ('core', _('Fetching publications from CORE')),
   ('oai', _('Fetching publications from OAI-PMH')),
   ('clustering', _('Clustering publications')),
   ('stats', _('Updating statistics')),
   ]


class Institution(models.Model):
    """
    A university or research institute.
    """
    #: The full name of the institution
    name = models.CharField(max_length=300)
    #: A list of identifiers for the institution (eg: ringgold-2167 for MIT)
    identifiers = ArrayField(models.CharField(max_length=256), null=True, blank=True)
    #: Country code
    country = CountryField(null=True, blank=True)
    #: Coordinates
    coords = PointField(null=True, blank=True)

    #: :py:class:`AccessStatistics` about the papers authored in this institution.
    stats = models.ForeignKey(AccessStatistics, null=True, blank=True)

    @property
    def sorted_departments(self):
        """
        Departments belonging to this institution, sorted by name.
        """
        return self.department_set.order_by('name')

    def __unicode__(self):
        return self.name

    def update_stats(self):
        """
        Refreshes the institution-level access statistics.
        """
        if not self.stats:
            self.stats = AccessStatistics.objects.create()
            self.save()
        from papers.models import Paper
        sqs = SearchQuerySet().models(Paper).filter(institutions=self.id)
        self.stats.update_from_search_queryset(sqs)

    @property
    def object_id(self):
        """
        Criteria to use in the search view to filter on this department
        """
        return "institution=%d" % self.pk

    @property
    def url(self):
        """
        The URL of the main page (list of departments for this institution).
        """
        return reverse('institution', args=[self.pk, self.slug])

    @property
    def slug(self):
        return slugify(self.name)

    def breadcrumbs(self):
        return [(unicode(self), self.url)]

    @property
    def sorted_researchers(self):
        """
        List of :py:class:`Researcher` who are directly affiliated to
        this institution, without department.
         sorted by last name (prefetches their stats as well)
        """
        return self.researcher_set.select_related('name', 'stats').order_by('name')

    @classmethod
    def create(cls, dct):
        """
        Given a dictionary representing an institution,
        as returned by OrcidProfile.institution,
        save the institution in the DB (or return
        an existing duplicate).

        The dictionary should contain 'name' and 'country'
        values, and possibly an identifier (such as a Ringgold one).

        Returns None if the institution is invalid
        (invalid country code, name too long…)
        """
        # cleanup arguments
        dct['name'] = dct['name'].strip()
        dct['country'] = dct['country'].strip()
        # django_countries does not validate the countries
        # against the list it contains (!?)
        if dct['country'] not in dict(countries):
            return

        # create a list of identifiers for this institution
        identifiers = []
        # add the 'fingerprint' for that institution
        identifiers.append(
            dct['country']+':'+iunaccent(dct['name']))
        # maybe add a disambiguated identifier
        if dct.get('identifier'):
            identifiers.append(
                dct.get('identifier'))

        # this uses our GIN index on identitfiers
        matches = Institution.objects.filter(
            identifiers__overlap=identifiers)

        try:
            if not matches:
                i = cls(
                    name=dct['name'],
                    country=dct['country'],
                    identifiers=identifiers)
                i.save()
                return i
            else:
                # TODO case where there are multiple matches : merge
                i = matches[0]
                old_identifiers = set(i.identifiers or [])
                new_identifiers = old_identifiers | set(identifiers)
                if old_identifiers != new_identifiers:
                    i.identifiers = list(new_identifiers)

                    # shorter names are better
                    if len(dct['name']) < len(i.name):
                        i.name = dct['name']
                    i.save()
                return i
        except DataError: # did not fit in the DB
            pass

    def merge(self, i):
        """
        Merges another institution into self
        """
        if len(i.name) < len(self.name):
            self.name = i.name
        self.identifiers = list(set(self.identifiers)|
                             set(i.identifiers))
        self.save()
        i.researcher_set.all().update(institution=self)
        i.department_set.all().update(institution=self)
        i.delete()

    def update_coords(self, sleep_time=5):
        """
        Attempts to fetch the position of the institution
        via OpenStreetMap Nominatim.
        """
        import requests
        r = requests.get('http://nominatim.openstreetmap.org/search/',
            params={
            'q':self.name,
            'countrycodes':self.country.code,
            'format':'json'})
        data = r.json()

        if(len(data) > 0):
            longitude = data[0]['lat']
            latitude = data[0]['lon']
            self.coords = {'type':'Point','coordinates':
                        [float(latitude),float(longitude)]}
            self.save(update_fields=['coords'])

        if sleep_time:
            from time import sleep
            sleep(sleep_time)



class Department(models.Model):
    """
    A department in an institution. Each :py:class:`Researcher` is affiliated with exactly one department.
    :param name: the full name of the department
    """

    #: The full name of the department
    name = models.CharField(max_length=300)
    #: The institution it belongs to
    institution = models.ForeignKey(Institution)

    #: :py:class:`AccessStatistics` about the papers authored in this department
    stats = models.ForeignKey(AccessStatistics, null=True, blank=True)

    @property
    def sorted_researchers(self):
        """List of :py:class:`Researcher` in this department sorted by last name (prefetches their stats as well)"""
        return self.researcher_set.select_related('name', 'stats').order_by('name')
    def __unicode__(self):
        return self.name

    def update_stats(self):
        """Refreshes the department-level access statistics for that department."""
        if not self.stats:
            self.stats = AccessStatistics.objects.create()
            self.save()
        self.stats.clear()
        for r in self.sorted_researchers:
            self.stats.add(r.stats)
        self.stats.save()

    @property
    def object_id(self):
        """
        Criteria to use in the search view to filter on this department
        """
        return "department=%d" % self.pk

    @property
    def url(self):
        """
        The URL of the main page (list of researchers) for this department.
        """
        return reverse('department', args=[self.pk])

    def breadcrumbs(self):
        return self.institution.breadcrumbs()+[(unicode(self), self.url)]


class NameVariant(models.Model):
    """
    A NameVariant is a binary relation between names and researchers. When present, it indicates
    that a given name is a possible name for the researcher. The confidence that papers with that
    name are authored by the given researcher is indicated by a confidence score.
    """

    #: The :py:class:`Name` that is part of the relation
    name = models.ForeignKey('Name')
    #: The :py:class:`Researcher` to which the name is attributed
    researcher = models.ForeignKey('Researcher')
    #: The similarity score between this name and one of the reference names for this researcher
    confidence = models.FloatField(default=1.)

    class Meta:
        unique_together = (('name', 'researcher'),)


class Researcher(models.Model):
    """
    A model to represent a researcher
    """

    #: The preferred :py:class:`Name` for this researcher
    name = models.ForeignKey('Name')
    #: It can be associated to a user
    user = models.ForeignKey(User, null=True, blank=True)
    #: It can be affiliated to a department
    department = models.ForeignKey(Department, null=True,
                                on_delete=models.SET_NULL)
    #: Or directly to an institution
    institution = models.ForeignKey(Institution, null=True,
                                on_delete=models.SET_NULL)

    # Various info about the researcher (not used internally)
    #: Email address for this researcher
    email = models.EmailField(blank=True, null=True)
    #: URL of the homepage
    homepage = models.URLField(max_length=1024, blank=True, null=True)
    #: Grade (student, post-doc, professor…)
    role = models.CharField(max_length=128, null=True, blank=True)
    #: ORCiD identifier
    orcid = models.CharField(max_length=32, null=True, blank=True, unique=True)
    #: Did we manage to import at least one record from the ORCID profile? (Null if we have not tried)
    empty_orcid_profile = models.NullBooleanField()

    # Fetching
    #: Last time we harvested publications for this researcher
    last_harvest = models.DateTimeField(null=True, blank=True)
    #: Task id of the harvester (if any)
    harvester = models.CharField(max_length=512, null=True, blank=True)
    #: Current subtask of the harvester
    current_task = models.CharField(
        max_length=64, choices=HARVESTER_TASK_CHOICES, null=True, blank=True)

    #: Statistics of papers authored by this researcher
    stats = models.ForeignKey(AccessStatistics, null=True)

    @property
    def slug(self):
        return slugify(self.name)

    def __unicode__(self):
        if self.name_id:
            return unicode(self.name)
        else:
            return 'Unnamed researcher'

    @property
    def url(self):
        return reverse('researcher', kwargs={'researcher': self.pk, 'slug': self.slug})

    @property
    def papers(self):
        """
        :py:class:`Paper` objects for this researcher,
        sorted by decreasing publication date
        """
        return Paper.objects.filter(
                authors_list__contains=[{'researcher_id': self.id}]
                          ).order_by('-pubdate')

    @property
    def matching_papers_url(self):
        """
        URL of the search page for papers with a matching name
        """
        return reverse('search')+'?'+urlencode({'authors': self.name.full})

    @property
    def name_variants(self):
        """
        All the names found in papers that could belong to the researcher.
        Among these names, at least the preferred :py:attr:`name`
        should have confidence 1.0 (other names can have confidence 1.0 if
        multiple names are known. The other names have been found in publications
        and are similar to one of these 1.0 confidence name variants.
        """
        return NameVariant.objects.filter(researcher=self)

    def add_name_variant(self, name, confidence, force_update=False):
        """
        Add a name variant with the given confidence and update
        the best_confidence field of the name accordingly.

        :param force_update: set the best_confidence even if the current value is
            higher.
        """
        if name.id is None:
            name.save()
        NameVariant.objects.get_or_create(
                name=name, researcher=self, defaults={'confidence': confidence})
        if name.best_confidence < confidence or force_update:
            name.best_confidence = confidence
            name.save(update_fields=['best_confidence'])

    def update_stats(self):
        """Update the access statistics for the papers authored by this researcher"""
        print "Researcher.update_stats should not be used anymore"
        #if not self.stats:
        #    self.stats = AccessStatistics.objects.create()
        #    self.save()
        #self.stats.update(self.papers)

    def fetch_everything(self):
        from backend.tasks import fetch_everything_for_researcher
        self.harvester = fetch_everything_for_researcher.delay(pk=self.id).id
        self.current_task = 'init'
        self.save(update_fields=['harvester', 'current_task'])

    def fetch_everything_if_outdated(self):
        if self.last_harvest is None or timezone.now() - self.last_harvest > PROFILE_REFRESH_ON_LOGIN:
            self.fetch_everything()

    def init_from_orcid(self):
        from backend.tasks import init_profile_from_orcid
        self.current_task = 'init'
        self.save(update_fields=['current_task'])
        self.harvester = getattr(init_profile_from_orcid.delay(pk=self.id),
'id', None)
        self.save(update_fields=['harvester'])

    @classmethod
    def get_or_create_by_orcid(cls, orcid, profile=None,
                    user=None, update=False, instance=settings.ORCID_BASE_DOMAIN):
        """
        Creates (or returns an existing) researcher from its ORCID id.

        :param profile: an :class:`OrcidProfile` object if it has already been fetched
                        from the API (otherwise we will fetch it ourselves)
        :param user: an user to associate with the profile.
        :param update: refresh researcher attributes even if it already exists
        :returns: a :class:`Researcher` if everything went well, raises MetadataSourceException otherwise
        """
        researcher = None
        if orcid is None:
            raise MetadataSourceException('Invalid ORCID id')

        researcher = None
        try:
            researcher = Researcher.objects.get(orcid=orcid)
        except Researcher.DoesNotExist:
            pass

        if researcher and not update:
            return researcher

        if profile is None:
            profile = OrcidProfile(orcid_id=orcid, instance=instance)
        else:
            profile = OrcidProfile(json=profile)
        name = profile.name
        homepage = profile.homepage
        if homepage:
            homepage = homepage[:1024]
        email = profile.email
        institution = profile.institution
        if institution:
            institution  = Institution.create(institution)

        if not researcher:
            researcher = Researcher.create_by_name(name[0], name[1], orcid=orcid,
                    user=user, homepage=homepage, email=email,
                    institution=institution)
        if not researcher:
            # invalid name?
            return

        # Ensure that extra info is added.
        name = Name.lookup_name(name)
        if not name:
            return

        save = False
        for kw, val in [('homepage', homepage),
                        ('orcid', orcid),
                        ('email', email),
                        ('institution', institution),
                        ('name', name)]:
            if getattr(researcher, kw) != val:
                setattr(researcher, kw, val)
                save = True
        if save:
            researcher.save()

        for variant in profile.other_names:
            confidence = name_similarity(variant, variant)
            name = Name.lookup_name(variant)
            if name is not None:
                researcher.add_name_variant(name, confidence)

        return researcher

    @classmethod
    def create_by_name(cls, first, last, **kwargs):
        """
        Creates a :class:`Researcher` with the given name.
        If an ORCID is provided, and a researcher with this ORCID already exists,
        this researcher will be returned. In any other case, a new researcher will be created.
        """
        name, _ = Name.get_or_create(first, last)
        if not name:
            return

        if kwargs.get('orcid') is not None:
            orcid = validate_orcid(kwargs['orcid'])
            if kwargs['orcid'] is None:
                raise ValueError('Invalid ORCiD: "%s"' % orcid)
            researcher, created = Researcher.objects.get_or_create(
                name=name, orcid=orcid, defaults=kwargs)
        else:
            args = kwargs.copy()
            args['name'] = name
            researcher = Researcher.objects.create(**args)

        return researcher

    @property
    def object_id(self):
        """Criteria to use in the search view to filter on this researcher"""
        return "researcher=%d" % self.pk

    def breadcrumbs(self):
        """
        We include the most detailed affiliation for the researcher
        """
        last = [(unicode(self), self.url)]
        # Institutions temporarily disabled while they are not populated
        #if self.department:
        #    return self.department.breadcrumbs()+last
        #elif self.institution:
        #    return self.institution.breadcrumbs()+last
        return last

    @cached_property
    def latest_paper(self):
        """
        Returns the latest paper authored by this researcher, if any.
        """
        lst = list(self.papers[:1])
        if lst:
            return lst[0]

    def affiliation_form(self):
        """
        Returns a form to change the affiliation of this researcher
        """
        from papers.forms import ResearcherDepartmentForm
        data = {'pk': self.id,
                'department': self.department_id}
        return ResearcherDepartmentForm(initial=data)


class Name(models.Model, BareName):
    first = models.CharField(max_length=MAX_NAME_LENGTH)
    last = models.CharField(max_length=MAX_NAME_LENGTH)
    full = models.CharField(max_length=MAX_NAME_LENGTH*2+1, db_index=True)
    best_confidence = models.FloatField(default=0.)

    class Meta:
        unique_together = ('first', 'last')
        ordering = ['last', 'first']

    @property
    def is_known(self):
        """
        Does this name belong to at least one known :class:`Researcher`?
        """
        return self.best_confidence > 0.

    @classmethod
    def get_or_create(cls, first, last):
        """
        Replacement for the regular get_or_create, so that the full
        name is built based on first and last
        """
        if not first and not last:
            return (None, False)

        n = cls.create(first, last)

        # Do this check after escaping, because this migth expand the
        # name.
        if (len(n.first or '') >= MAX_NAME_LENGTH-1 or
            len(n.last or '') >= MAX_NAME_LENGTH-1):
            return (None, False)

        return cls.objects.get_or_create(full=n.full[:255],
                                         defaults={'first': n.first, 'last': n.last})

    @classmethod
    def lookup_name(cls, author_name):
        """
        Lookup a name (pair of (first,last)) in the model.
        If there is already such a name in the database, returns it,
        otherwise creates one properly.

        In addition to `get_or_create`, this looks for relevant researchers
        whose name might match this one.
        """
        if author_name == None:
            return
        n, _ = cls.get_or_create(author_name[0], author_name[1])
        return n

    @classmethod
    def from_bare(cls, bare_name):
        """
        Calls `lookup_name` for the given `bare_name`, if it is indeed bare..
        """
        if hasattr(bare_name, 'id'):
            return bare_name  # not so bare…
        return cls.lookup_name((bare_name.first, bare_name.last))

    def save_if_not_saved(self):
        """
        Used to save unsaved names after lookup
        """
        if self.pk is None:
            # the best_confidence field should already be up to date as it is
            # computed in the lookup
            self.save()

    @property
    def object_id(self):
        """Criteria to use in the search view to filter on this name"""
        return "name=%d" % self.pk


# Max number of OaiRecord per Paper:
# beyond that, we ignore them.
MAX_OAIRECORDS_PER_PAPER = 100

# Papers matching one or more researchers
class Paper(models.Model, BarePaper):
    title = models.CharField(max_length=1024)
    fingerprint = models.CharField(max_length=64, unique=True)
    date_last_ask = models.DateField(null=True)  # TODO remove (unused)

    #: Approximate publication date.
    #: For instance if we only know it is in 2014 we'll put 2014-01-01
    pubdate = models.DateField()

    #: Full list of authors for this paper
    authors_list = JSONField(default=list)

    last_modified = models.DateTimeField(auto_now=True, db_index=True)
    visible = models.BooleanField(default=True)
    last_annotation = models.CharField(max_length=32, null=True, blank=True)

    doctype = models.CharField(
        max_length=64, null=True, blank=True, choices=PAPER_TYPE_CHOICES)

    # The two following fields need to be updated after the relevant changes
    # using the methods below.
    oa_status = models.CharField(
        max_length=32, null=True, blank=True, default='UNK')
    pdf_url = models.URLField(max_length=2048, null=True, blank=True)

    # Task id of the current task updating the metadata of this article (if any)
    task = models.CharField(max_length=512, null=True, blank=True)

    def __init__(self, *args, **kwargs):
        super(Paper, self).__init__(*args, **kwargs)
        self.just_created = False
        self.cached_oairecords = None

    ### Relations to other models, reimplemented from :class:`BarePaper` ###

    @property
    def authors(self):
        """
        The author sorted as they should appear. Their names are pre-fetched.
        """
        return map(BareAuthor.deserialize, self.authors_list)

    def author_name_pairs(self):
        """
        The authors' names, represented as (first,last) pairs.
        """
        return [(a.name.first,a.name.last) for a in self.authors]

    @property
    def publications(self):
        """
        The list of publications associated with this paper, returned
        as a queryset.
        """
        return self.oairecord_set.filter(journal_title__isnull=False,
                                         publisher_name__isnull=False)

    @property
    def oairecords(self):
        """
        The list of OAI records associated with this paper, returned
        as a queryset.
        """
        if self.cached_oairecords is not None:
            return self.cached_oairecords
        # we don't update the cache yet as it would fetch the queryset
        # straight away
        return self.oairecord_set.all()

    def cache_oairecords(self):
        """
        Fetches once the cache for child OaiRecords.
        The reason why we're not doing this explicitly in self.oairecords
        is that sometimes we need fresh oairecords and so caching is
        not always desirable.
        """
        self.cached_oairecords = list(self.oairecord_set.all())

    @property
    def researcher_ids(self):
        """
        The list of researcher ids associated with this paper,
        returned as a list.
        """
        return [ a['researcher_id'] for a in self.authors_list
                 if a.get('researcher_id') is not None]

    @property
    def researchers(self):
        """
        The list of researchers associated with this paper, returned
        as a list of Researcher instances.
        """
        return [ Researcher.objects.get(id=rid)
                 for rid in self.researcher_ids ]

    def add_author(self, author, position=None):
        """
        Add an author at the end of the authors list by default
        or at the specified position.

        The change is not commited to the database
        (you need to call save() afterwards).

        :param position: add the author at that index.
        """
        author_serialized = author.serialize()
        if position is None:
            position = len(self.authors_list)
        self.authors_list.insert(position, author_serialized)
        return author

    def set_researcher(self, position, researcher_id):
        """
        Sets the researcher_id for the author at the given position
        (0-indexed).
        researcher_id can be set to None to unaffiliate an author
        with a researcher.
        """
        if position < 0 or position > len(self.authors_list):
            raise ValueError('Invalid position provided')
        self.authors_list[position]['researcher_id'] = researcher_id
        self.save(update_fields=['authors_list'])

    def add_oairecord(self, oairecord):
        """
        Adds a record (possibly bare) to the paper, by saving it in
        the database
        """
        # Clean up the record
        oairecord.cleanup_description()

        # Test first if there is no other record with this DOI
        doi = oairecord.doi
        if doi:
            matches = OaiRecord.objects.filter(doi=doi)[:1]
            if matches:
                rec = matches[0]
                if rec.about != self:
                    # we delete self
                    # and keep rec.about, so that the oldest paper
                    # is kept (otherwise, we break links!)
                    rec.about.merge(self)
                self.just_created = False

        rec = OaiRecord.new(about=self,
                            **oairecord.__dict__)
        self.just_created = False
        return rec

    ### Paper creation ###

    @classmethod
    def get_or_create(cls, title, author_names, pubdate, visible=True, affiliations=None):
        """
        Creates an (initially) bare paper and saves it to the database.

        :returns: the corresponding :class:`Paper` instance.
        """
        p = BarePaper.create(title, author_names, pubdate,
                             visible, affiliations)
        return cls.from_bare(p)

    @classmethod
    def find_by_fingerprint(cls, fp):
        return Paper.objects.filter(fingerprint__exact=fp)

    @classmethod
    def from_bare(cls, paper):
        """
        Saves a paper to the database if it is not already present.
        The clustering algorithm is run to decide what authors should be
        attributed to the paper.

        :returns: the :class:`Paper` instance created from the bare paper supplied.
        """
        try:
            # Look up the fingerprint
            fp = paper.fingerprint
            matches = Paper.find_by_fingerprint(fp)

            p = None
            if matches:  # We have found a paper matching the fingerprint
                p = matches[0]
                if paper.visible and not p.visible:
                    p.visible = True
                p.update_authors(
                        paper.authors,
                        save_now=False)
                for record in paper.oairecords:
                    p.add_oairecord(record)
                p.update_availability()  # in Paper, this saves to the db
            else:  # Otherwise we create a new paper
                # this already saves the paper in the db
                p = super(Paper, cls).from_bare(paper)

            return p

        except DataError as e:
            raise ValueError(
                'Invalid paper, does not fit in the database schema:\n'+unicode(e))

    ### Other methods, specific to this non-bare subclass ###

    def update_author_stats(self):
        """
        Updates the statistics of all researchers identified for this paper
        """
        for author in self.authors:
            if author.researcher:
                author.researcher.update_stats()

    def already_asked_for_upload(self):
        if self.date_last_ask == None:
            return False
        else:
            return ((datetime.now().date() - self.pubdate) <= timedelta(days=10))

    def can_be_asked_for_upload(self):
        return ((self.pdf_url == None) and
                (self.oa_status == 'OK') and
                not(self.already_asked_for_upload()) and
                not(self.author_set.filter(researcher__isnull=False) == []))

    @cached_property
    def owners(self):
        """
        Returns the list of users that own this paper (listed as authors and identified as such).
        """
        users = []
        for a in self.authors:
            if a.researcher and a.researcher.user:
                users.append(a.researcher.user)
        return users

    def can_be_claimed_by(self, user):
        """
        Is it possible for user to claim this paper?
        """
        for author in self.authors:
            first_name = None
            last_name = None
            try:
                first_name = user.first_name
                last_name = user.last_name
            except AttributeError:
                # anonymous user
                return False
            if not match_names(author.name.pair,
                               (first_name, last_name)):
                continue
            if author.orcid:
                continue
            if author.researcher_id:
                continue
            return True
        return False

    def unclaim_for(self, user):
        """
        Remove all associations between this paper and user
        """
        try:
            user_researcher = Researcher.objects.get(user=user)
        except Researcher.DoesNotExist:
            user_researcher = None
        user_orcid = None
        if user_researcher:
            user_orcid = user_researcher.orcid
        for idx, author in enumerate(self.authors):
            if (author.orcid == user_orcid or author.researcher_id ==
                    user_researcher.id):
                # remove association between this author and user
                self.authors_list[idx]['orcid'] = None
                self.authors_list[idx]['researcher_id'] = None
                self.save()
                self.update_index()
                return True
        # nothing was done, paper cannot be unclaimed
        raise False

    def claim_for(self, user):
        """
        Associate this paper to the requested user
        """
        if user in self.owners:
            # user already owns the paper
            return False
        try:
            user_researcher = Researcher.objects.get(user=user)
        except Researcher.DoesNotExist:
            user_researcher = None
        user_orcid = None
        if user_researcher:
            user_orcid = user_researcher.orcid
        for idx, author in enumerate(self.authors):
            if not match_names(author.name.pair,
                               (user.first_name, user.last_name)):
                continue
            if author.orcid:
                continue
            if author.researcher_id:
                continue
            self.authors_list[idx]['orcid'] = user_orcid
            self.authors_list[idx]['researcher_id'] = user_researcher.id
            self.save()
            self.update_index()
            return True
        # paper cannot be claimed by user
        raise ValueError

    def is_owned_by(self, user, flexible=False):
        """
        Is this user one of the owners of that paper?

        :param flexible: if set to true, we will also accept the user
            as owner if its name matches any of the author names.
        """
        owned = user in self.owners
        if not owned and flexible:
            user_name = (user.first_name, user.last_name)
            return any(match_names(a, user_name)
                   for a in self.author_name_pairs())
        return owned

    @cached_property
    def is_deposited(self):
        return self.successful_deposits().count() > 0

    def update_availability(self, cached_oairecords=[]):
        """
        Updates the :class:`Paper`'s own `pdf_url` field
        based on its sources (:class:`OaiRecord`).

        This uses a non-trivial logic, hence it is useful to keep this result cached
        in the database row.

        :param cached_oairecords: if the list of oairecords
                to be considered is already available to the caller,
                it can pass it to this function to save a db query
        """
        super(Paper, self).update_availability(cached_oairecords)
        self.save()
        self.invalidate_cache()

    def status_helptext(self):
        """
        Helptext displayed next to the paper logo
        """
        return STATUS_CHOICES_HELPTEXT[self.combined_status]

    @property
    def combined_status(self):
        """
        The combined status of the paper (availability and policy)
        """
        return combined_status_for_instance(self)

    def consolidate_metadata(self, wait=True):
        """
        Tries to find an abstract for the paper, if none is available yet,
        possibly by fetching it from Zotero via doi-cache.
        """
        if self.task is None:
            from backend.tasks import consolidate_paper
            task = consolidate_paper.delay(pk=self.id)
            self.task = task.id
            self.save(update_fields=['task'])
        else:
            task = AsyncResult(self.task)
        if wait:
            task.get(timeout=10)
            self.task = None
            self.save(update_fields=['task'])

    def get_doi(self):
        """
        Returns any DOI associated to this Paper, None otherwise
        """
        for rec in self.oairecords:
            if rec.doi:
                return rec.doi

    @classmethod
    def create_by_doi(self, doi, bare=False):
        """
        Creates a paper given a DOI
        """
        import backend.crossref as crossref
        cr_api = crossref.CrossRefAPI()
        bare_paper = cr_api.create_paper_by_doi(doi)
        if bare:
            return bare_paper
        elif bare_paper:
            return Paper.from_bare(bare_paper)  # TODO index it?

    @classmethod
    def get_by_doi(cls, doi):
        """
        Finds the paper associated to that DOI (if any)
        """
        # there should not be more than one paper in this
        # queryset
        return cls.objects.filter(oairecord__doi=doi).first()

    @classmethod
    def create_by_hal_id(self, hal_id, bare=False):
        """
        Creates a paper given a HAL id (e.g. hal-01227383)
        """
        return self.create_by_oai_id(
            'ftccsdartic:oai:hal.archives-ouvertes.fr:'+hal_id,
            bare=bare)

    @classmethod
    def create_by_oai_id(self, oai_id, metadataPrefix='base_dc', bare=False):
        """
        Creates a paper by its OAI identifier.
        """
        from backend.oai import get_proaixy_instance
        oai = get_proaixy_instance()
        p = oai.create_paper_by_identifier(oai_id, metadataPrefix)
        if bare:
            return p
        elif p:
            return Paper.from_bare(p) # TODO index it?

    def successful_deposits(self):
        return self.depositrecord_set.filter(oairecord__isnull=False)

    def invalidate_cache(self):
        """
        Invalidate the HTML cache for all the publications of this researcher.
        """
        for a in self.authors+[None]:
            rpk = None
            if a:
                if a.researcher_id is None:
                    continue
                else:
                    rpk = a.researcher_id
            for lang in POSSIBLE_LANGUAGE_CODES:
                key = make_template_fragment_key(
                    'publiListItem', [self.pk, lang, rpk])
                cache.delete(key)

    def update_authors(self,
                       new_authors,
                       save_now=True):
        """
        Improves the current list of authors by considering a new list of author names.
        Missing authors are added, and names are unified.
        If affiliations are provided, they will replace the old ones if they are
        more informative.

        :param authors: list of BareAuthor instances (the order matters)
        """
        old_authors = list(self.authors)

        # Invalidate cached properties
        if hasattr(self, 'interesting_authors'):
            del self.interesting_authors

        new_author_names = [(a.name.first, a.name.last) for a in
                            new_authors]

        old_names = [(a.name.first, a.name.last) for a in old_authors]
        unified_names = unify_name_lists(old_names, new_author_names)

        unified_authors = []
        for new_name, (old_idx, new_idx) in unified_names:
            if new_name is None:
                # skip duplicate names
                continue

            # Create the author
            author = None
            if old_idx is not None:
                # this name is associated with an existing author
                # so we keep it
                author = old_authors[old_idx]
            else:
                author = new_authors[new_idx]

            # update attributes
            author.name = BareName.create_bare(first=new_name[0],
                                               last=new_name[1])
            if new_idx is not None and affiliation_is_greater(
                    new_authors[new_idx].affiliation,
                    author.affiliation):
                author.affiliation = new_authors[new_idx].affiliation
            if new_idx is not None and new_authors[new_idx].orcid:
                author.orcid = new_authors[new_idx].orcid

            unified_authors.append(author.serialize())
        self.authors_list = unified_authors
        if save_now:
            self.save(update_fields=['authors_list'])

    def merge(self, paper):
        """
        Merges another paper into self. This deletes the other paper.
        We do our best to unify all the metadata parts, but of course
        there will always be some mistakes as there is no way to find out
        which metadata part is best in general.

        :param paper: The second paper to merge and delete.
        """

        if self.pk == paper.pk:
            return

        self.visible = paper.visible or self.visible

        OaiRecord.objects.filter(about=paper.pk).update(about=self.pk)
        self.update_authors(paper.authors, save_now=False)

        paper.invalidate_cache()

        # create a copy of the paper to delete,
        # so that the instance we have got as argument
        # is not invalidated
        copied = Paper()
        copied.__dict__.update(paper.__dict__)
        copied.delete()

        paper.id = self.id
        self.update_availability()

    def recompute_fingerprint_and_merge_if_needed(self):
        """
        Recomputes the fingerprint based on the new
        values of the paper's attributes, checks whether
        there is already another paper with the same fingerprint,
        and if so merge them.
        """
        new_fingerprint = self.new_fingerprint()
        if self.fingerprint == new_fingerprint:
            return
        match = Paper.objects.filter(fingerprint=new_fingerprint).first()
        if match is None:
            self.fingerprint = new_fingerprint
            self.save(update_fields=['fingerprint'])
            return
        else:
            match.merge(self)
            return match

    def update_visible(self):
        """
        Should this paper be shown to users?
        """
        old_visible = self.visible
        super(Paper, self).update_visible()
        if self.visible != old_visible:
            self.save(update_fields=['visible'])

    def breadcrumbs(self):
        """
        Returns the navigation path to the paper, for display as breadcrumbs in the template.
        """
        first_researcher = None
        for author in self.authors:
            if author.researcher:
                first_researcher = author.researcher
                break
        result = []
        if first_researcher is None:
            result.append((_('Papers'), reverse('search')))
        else:
            result.append((unicode(first_researcher), first_researcher.url))
        result.append((self.citation, self.url))
        return result

    @property
    def url(self):
        return reverse('paper', args=[self.pk, self.slug])

    def can_be_deposited(self, user):
        """
        Returns true when this paper can be deposited
        in at least one repository configured on this
        Dissemin instance.
        """
        from deposit.views import get_all_repositories_and_protocols
        l = get_all_repositories_and_protocols(self, user)
        return any([proto for _, proto in l])

    def remove_from_index(self):
        """
        Remove this paper from Haystack's index
        (to be called before deleting the paper for real)
        """
        using_backends = haystack.connection_router.for_write(instance=self)
        for using in using_backends:
            try:
                index = haystack.connections[using].get_unified_index(
                                        ).get_index(Paper)
                index.remove_object(self, using=using)
            except haystack.exceptions.NotHandled:
                pass

    def update_index(self):
        """
        Updates Haystack's index for this paper
        """
        using_backends = haystack.connection_router.for_write(instance=self)
        for using in using_backends:
            try:
                index = haystack.connections[using].get_unified_index(
                                        ).get_index(Paper)
                index.update_object(self, using=using)
            except haystack.exceptions.NotHandled:
                pass

# Rough data extracted through OAI-PMH

class OaiSourceManager(CachingManager):
    def get_by_natural_key(self, identifier):
        return self.get(identifier=identifier)

class OaiSource(CachingMixin, models.Model):
    objects = OaiSourceManager()

    identifier = models.CharField(max_length=300, unique=True)
    name = models.CharField(max_length=100)
    oa = models.BooleanField(default=False)
    priority = models.IntegerField(default=1)
    default_pubtype = models.CharField(
        max_length=64, choices=PAPER_TYPE_CHOICES)

    # Fetching properties
    last_status_update = models.DateTimeField(auto_now=True)

    def __unicode__(self):
        return self.name

    def natural_key(self):
        return (self.identifier,)

    class Meta:
        verbose_name = "OAI source"


class OaiRecord(models.Model, BareOaiRecord):
    source = models.ForeignKey(OaiSource)
    about = models.ForeignKey(Paper)

    identifier = models.CharField(max_length=512, unique=True)
    splash_url = models.URLField(max_length=1024, null=True, blank=True)
    pdf_url = models.URLField(max_length=1024, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    keywords = models.TextField(null=True, blank=True)
    contributors = models.CharField(max_length=4096, null=True, blank=True)
    pubtype = models.CharField(
        max_length=64, null=True, blank=True, choices=PAPER_TYPE_CHOICES)

    # this is actually the *journal* title
    journal_title = models.CharField(max_length=512, blank=True, null=True)
    container = models.CharField(max_length=512, blank=True, null=True)
    journal = models.ForeignKey(Journal, blank=True, null=True)

    publisher = models.ForeignKey(Publisher, blank=True, null=True)
    publisher_name = models.CharField(max_length=512, blank=True, null=True)

    issue = models.CharField(max_length=64, blank=True, null=True)
    volume = models.CharField(max_length=64, blank=True, null=True)
    pages = models.CharField(max_length=64, blank=True, null=True)
    pubdate = models.DateField(blank=True, null=True)

    # in theory, there is no limit
    doi = models.CharField(max_length=1024, blank=True,
                           null=True, db_index=True)

    last_update = models.DateTimeField(auto_now=True)

    # Cached version of source.priority
    priority = models.IntegerField(default=1)

    def update_priority(self):
        super(OaiRecord, self).update_priority()
        self.save(update_fields=['priority'])

    @classmethod
    def new(cls, **kwargs):
        """
        Creates a new OAI record by checking first for duplicates and
        updating them if necessary.
        """
        source = None
        if kwargs.get('source') is None:
            source_id = kwargs.get('source_id')
            try:
                source = OaiSource.objects.get(id=source_id)
            except ObjectDoesNotExist:
                pass
            if source is None:
                raise ValueError('No source provided to create the OAI record.')
        else:
            source = kwargs['source']
        if kwargs.get('identifier') is None:
            raise ValueError('No identifier provided to create the OAI record.')
        identifier = kwargs['identifier']
        if kwargs.get('about') is None:
            raise ValueError('No paper provided to create the OAI record.')
        about = kwargs['about']
        if kwargs.get('splash_url') is None:
            raise ValueError('No URL provided to create the OAI record.')
        splash_url = kwargs['splash_url']
        pdf_url = kwargs.get('pdf_url')

        # Has the paper we are trying to add a record to been just
        # created? If so, we should not search for duplicate records in
        # the paper itself.
        match = None
        if not about.just_created:
            # Search for duplicate records
            match = OaiRecord.find_duplicate_records(
                    about,
                    splash_url,
                    pdf_url)

        # We check that there are not already too many records in this
        # paper
        if about.cached_oairecords and len(about.cached_oairecords) >= MAX_OAIRECORDS_PER_PAPER:
            raise ValueError('Too many records in paper %d' % about.pk)

        # We don't search for records with the same identifier yet,
        # we will rather catch the exception thrown by the DB
        if not match:
            same_identifier = OaiRecord.objects.filter(identifier=identifier)
            if same_identifier:
                match = same_identifier[0]

        if not match:
            # Otherwise create a new record
            record = OaiRecord(
                    source=source,
                    identifier=identifier,
                    splash_url=splash_url,
                    pdf_url=pdf_url,
                    about=about,
                    description=kwargs.get('description'),
                    keywords=kwargs.get('keywords'),
                    contributors=kwargs.get('contributors'),
                    pubtype=kwargs.get('pubtype', source.default_pubtype),
                    priority=source.priority,
                    journal_title=kwargs.get('journal_title'),
                    container=kwargs.get('container'),
                    publisher_name=kwargs.get('publisher_name'),
                    issue=kwargs.get('issue'),
                    volume=kwargs.get('volume'),
                    pages=kwargs.get('pages'),
                    doi=kwargs.get('doi'),
                    publisher=kwargs.get('publisher'),
                    journal=kwargs.get('journal'),
                    )
            # with transaction.atomic():
            record.save()

            if about.cached_oairecords is not None:
                about.cached_oairecords.append(record)

            return record

        # Update the duplicate if necessary
        if match:
            changed = False

            if pdf_url != None and (match.pdf_url == None or
                                    (match.pdf_url != pdf_url and match.priority < source.priority)):
                match.source = source
                match.priority = source.priority
                match.pdf_url = pdf_url
                match.splash_url = splash_url
                changed = True

            def update_field_conditionally(field):
                global changed
                new_val = kwargs.get(field, '')
                if new_val and (not match.__dict__[field] or
                                len(match.__dict__[field]) < len(new_val)):
                    match.__dict__[field] = new_val
                    changed = True

            update_field_conditionally('contributors')
            update_field_conditionally('keywords')
            update_field_conditionally('description')
            update_field_conditionally('doi')

            new_pubdate = kwargs.get('pubdate')
            if new_pubdate and match.about.pubdate > new_pubdate:
                match.about.pubdate = new_pubdate
                match.save(update_fields=['pubdate'])

            new_pubtype = kwargs.get('pubtype', source.default_pubtype)
            if new_pubtype in PAPER_TYPE_PREFERENCE:
                idx = PAPER_TYPE_PREFERENCE.index(new_pubtype)
                old_idx = len(PAPER_TYPE_PREFERENCE)-1
                if match.pubtype in PAPER_TYPE_PREFERENCE:
                    old_idx = PAPER_TYPE_PREFERENCE.index(match.pubtype)
                if idx < old_idx:
                    changed = True
                    match.pubtype = PAPER_TYPE_PREFERENCE[idx]

            if changed:
                try:
                    match.save()

                    if about.cached_oairecords is not None:
                        for i, rec in enumerate(about.cached_oairecords):
                            if rec.pk == match.pk:
                                about.cached_oairecords[i] = rec

                except DataError as e:
                    raise ValueError(
                        'Unable to create OAI record:\n'+unicode(e))

            if about.pk != match.about.pk:
                match.about.merge(about)

            return match

    @classmethod
    def find_duplicate_records(cls, paper, splash_url, pdf_url):
        """
        Finds duplicate OAI records. These duplicates can have a different identifier,
        or slightly different urls (for instance https:// instead of http://).

        :param paper: the :class:`Paper` the record is about
        :param splash_url: the splash url of the target record (link to the metadata page)
        :param pdf_url: the url of the PDF, if known (otherwise `None`)
        """
        https_re = re.compile(r'https?(.*)')

        def shorten(url):
            """
            removes the 'https?' prefix or converts to DOI
            """
            if not url:
                return
            doi = to_doi(url)
            if doi:
                return doi
            match = https_re.match(url.strip())
            if match:
                return match.group(1)

        short_splash = shorten(splash_url)
        short_pdf = shorten(pdf_url)

        if short_splash == None or paper == None:
            return

        records = list(paper.oairecord_set.all()[:MAX_OAIRECORDS_PER_PAPER])
        paper.cached_oairecords = records
        for record in records:
            short_splash2 = shorten(record.splash_url)
            short_pdf2 = shorten(record.pdf_url)
            if (short_splash == short_splash2 or
                (short_pdf is not None and
                 short_pdf2 == short_pdf)):
                return record

    class Meta:
        verbose_name = "OAI record"


def create_default_stats():
    return AccessStatistics.objects.create().pk


class PaperWorld(SingletonModel):
    """
    A singleton to link to a special instance of AccessStatistics for all papers
    """
    stats = models.ForeignKey(AccessStatistics, default=create_default_stats)

    def update_stats(self):
        """Update the access statistics for all papers"""
        self.stats.update_from_search_queryset(SearchQuerySet().models(Paper))

    @property
    def object_id(self):
        return ''

    def __unicode__(self):
        return "All papers"

    class Meta(object):
        verbose_name = "Paper World"
