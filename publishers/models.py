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

from statistics.models import AccessStatistics

from django.apps import apps
from django.core.urlresolvers import reverse
from django.db import models
from django.template.defaultfilters import slugify
from django.utils.functional import cached_property
from django.utils.translation import ugettext as __
from django.utils.translation import ugettext_lazy as _
from search import SearchQuerySet

get_model = apps.get_model


OA_STATUS_CHOICES = (
        ('OA', _('Open access'), _('Freely available from the publisher.')),
        ('OK', _('Allows pre/post prints'),
         _('The publisher sells copies but allows authors to deposit some version of the article in a repository.')),
        ('NOK', _('Forbids pre/post prints'),
         _('The publisher forbids authors to deposit any version of their article online.')),
        ('UNK', _('Policy unclear'), _(
            'For complicated policies, unknown publishers and unpublished documents.')),
   )

POLICY_CHOICES = [('can', _('Allowed')),
                  ('cannot', _('Forbidden')),
                  ('restricted', _('Restricted')),
                  ('unclear', _('Unclear')),
                  ('unknown', _('Unknown'))]


OA_STATUS_PREFERENCE = [x[0] for x in OA_STATUS_CHOICES]
OA_STATUS_CHOICES_WITHOUT_HELPTEXT = [(x[0], x[1]) for x in OA_STATUS_CHOICES]


def publishers_breadcrumbs():
    return [(_('Publishers'), reverse('publishers'))]


class DummyPublisher(object):
    """
    Class representing an "unknown" publisher, which means a publisher
    with a name that did not return anything from SHERPA/RoMEO
    """
    pk = None
    preprint = 'unknown'
    postprint = 'unknown'
    pdfversion = 'unknown'
    preprint_conditions = []
    postprint_conditions = []
    pdfversion_conditions = []

    def __init__(self, name=None):
        if name is not None:
            self.name = name
        else:
            self.name = __('Unknown publisher')

    def __unicode__(self):
        return self.name

# Publisher associated with a journal


class Publisher(models.Model):
    """
    A publisher, as represented by SHERPA/RoMEO
    """
    romeo_id = models.CharField(max_length=64)
    name = models.CharField(max_length=256, db_index=True)
    alias = models.CharField(max_length=256, null=True, blank=True)
    url = models.URLField(null=True, blank=True)
    preprint = models.CharField(
        max_length=32, choices=POLICY_CHOICES, default='unknown')
    postprint = models.CharField(
        max_length=32, choices=POLICY_CHOICES, default='unknown')
    pdfversion = models.CharField(
        max_length=32, choices=POLICY_CHOICES, default='unknown')
    oa_status = models.CharField(
        max_length=32, choices=OA_STATUS_CHOICES_WITHOUT_HELPTEXT, default='UNK')

    stats = models.ForeignKey(AccessStatistics, null=True)

    class Meta:
        db_table = 'papers_publisher'

    def classify_oa_status(self):
        """
        Classify the publisher status into one of "OA" (gold open access), "OK" (self-archiving permitted for some version),
        "NOK" (self-archiving not allowed), "UNK" (unknown or unclear policy)..
        """
        status = 'UNK'
        lst = [self.preprint, self.postprint, self.pdfversion]
        if 'can' in lst:
            status = 'OK'
        elif 'cannot' in lst and all(map(lambda x: x == 'cannot' or x == 'unknown', lst)):
            status = 'NOK'

        for c in self.publishercondition_set.all():
            if c.text.lower() == 'all titles are open access journals':
                status = 'OA'
            elif 'doaj says it is an open access journal' in c.text.lower():
                status = 'OA'
        return status

    def update_stats(self):
        if not self.stats:
            self.stats = AccessStatistics.objects.create()
            self.save()
        from papers.models import Paper
        sqs = SearchQuerySet().models(Paper).filter(publisher=self.id)
        self.stats.update_from_search_queryset(sqs)

    def __unicode__(self):
        if not self.alias:
            return self.name
        else:
            return self.name+' ('+self.alias+')'

    @property
    def publi_count(self):
        # TODO ensure that the papers are not only visible,
        # but also assigned to a researcher
        if self.stats:
            return self.stats.num_tot
        return 0

    @property
    def sorted_journals(self):
        return self.journal_set.all().select_related('stats').filter(stats__num_tot__gt=0).order_by('-stats__num_tot')

    @cached_property
    def preprint_conditions(self):
        return list(self.publisherrestrictiondetail_set.filter(applies_to='preprint'))

    @cached_property
    def postprint_conditions(self):
        return list(self.publisherrestrictiondetail_set.filter(applies_to='postprint'))

    @cached_property
    def pdfversion_conditions(self):
        return list(self.publisherrestrictiondetail_set.filter(applies_to='pdfversion'))

    @cached_property
    def conditions(self):
        return list(self.publishercondition_set.all())

    @property
    def has_conditions(self):
        return len(self.conditions) > 0

    @cached_property
    def copyrightlinks(self):
        return list(self.publishercopyrightlink_set.all())

    @property
    def has_copyrightlinks(self):
        return len(self.copyrightlinks) > 0

    def change_oa_status(self, new_oa_status):
        if self.oa_status == new_oa_status:
            return
        self.oa_status = new_oa_status
        self.save()
        papers = get_model('papers', 'Paper').objects.filter(
            oairecord__publisher=self.pk)
        for p in papers:
            p.update_availability()
            p.invalidate_cache()

    def breadcrumbs(self):
        result = publishers_breadcrumbs()
        result.append((unicode(self), self.canonical_url))
        return result

    def json(self):
        """
        A JSON representation of the policy
        """
        return {'preprint': self.preprint,
                'postprint': self.postprint,
                'published': self.pdfversion,
                'romeo_id': self.romeo_id}

    @property
    def slug(self):
        return slugify(self.name)

    @property
    def canonical_url(self):
        return reverse('publisher', kwargs={'pk': self.pk, 'slug': self.slug})

# Journal data retrieved from RoMEO


class Journal(models.Model):
    title = models.CharField(max_length=256, db_index=True)
    last_updated = models.DateTimeField(auto_now=True)
    issn = models.CharField(max_length=10, blank=True, null=True, unique=True)
    publisher = models.ForeignKey(Publisher)

    stats = models.ForeignKey(AccessStatistics, null=True)

    def update_stats(self):
        if not self.stats:
            self.stats = AccessStatistics.objects.create()
            self.save()
        from papers.models import Paper
        sqs = SearchQuerySet().models(Paper).filter(journal=self.id)
        self.stats.update_from_search_queryset(sqs)

    def breadcrumbs(self):
        return self.publisher.breadcrumbs()+[(unicode(self), '')]

    def __unicode__(self):
        return self.title

    class Meta:
        ordering = ['title']
        db_table = 'papers_journal'


class PublisherCondition(models.Model):
    publisher = models.ForeignKey(Publisher)
    text = models.CharField(max_length=1024)

    def __unicode__(self):
        return self.text

    class Meta:
        db_table = 'papers_publishercondition'


class PublisherCopyrightLink(models.Model):
    publisher = models.ForeignKey(Publisher)
    text = models.CharField(max_length=256)
    url = models.URLField()

    def __unicode__(self):
        return self.text

    class Meta:
        db_table = 'papers_publishercopyrightlink'


class PublisherRestrictionDetail(models.Model):
    publisher = models.ForeignKey(Publisher)
    text = models.CharField(max_length=256)
    applies_to = models.CharField(max_length=32)

    def __unicode__(self):
        return self.text

    class Meta:
        db_table = 'papers_publisherrestrictiondetail'

# Counts the number of times a given publisher string has
# been associated with a model publisher


class AliasPublisher(models.Model):
    publisher = models.ForeignKey(Publisher)
    name = models.CharField(max_length=512)
    count = models.IntegerField(default=0)
    unique_together = ('name', 'publisher')

    def __unicode__(self):
        return self.name + ' --'+str(self.count)+'--> '+unicode(self.publisher)

    @classmethod
    def increment(cls, name, publisher):
        # TODO it would be more efficient with an update, but it does not really
        # work
        if not name:
            return
        alias, _ = cls.objects.get_or_create(
            name=name, publisher=publisher)
        alias.count += 1
        alias.save()

    class Meta:
        db_table = 'papers_aliaspublisher'
