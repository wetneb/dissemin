# -*- encoding: utf-8 -*-

# Dissemin: open access policy enforcement tool
# Copyright (C) 2014 Antonin Delpeuch
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

from __future__ import absolute_import
from __future__ import unicode_literals

from statistics.models import AccessStatistics

from backend.zotero import consolidate_publication
from backend.orcid import OrcidPaperSource
from backend.crossref import CrossRefAPI
from backend.utils import run_only_once
from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone
from papers.errors import MetadataSourceException
from papers.models import Paper
from papers.models import PaperWorld
from papers.models import Researcher
from papers.models import Institution
from publishers.models import Journal
from publishers.models import Publisher

logger = get_task_logger(__name__)


def update_researcher_task(r, task_name):
    """
    Update the task identifier associated to a given researcher.
    This also updates the 'last_harvest' field.
    """
    r.current_task = task_name
    r.last_harvest = timezone.now()
    r.save(update_fields=['current_task', 'last_harvest'])


@shared_task(name='init_profile_from_orcid')
@run_only_once('researcher', keys=['pk'])
def init_profile_from_orcid(pk):
    """
    Populates the profile from ORCID and Crossref

    This task is intended to be very quick, so that users
    can see their ORCID publications quickly.
    """
    r = Researcher.objects.get(pk=pk)
    update_task = lambda name: update_researcher_task(r, name)
    update_task('clustering')
    fetch_everything_for_researcher(pk)


@shared_task(name='fetch_everything_for_researcher')
@run_only_once('researcher', keys=['pk'], timeout=15*60)
def fetch_everything_for_researcher(pk):
    sources = [
        ('orcid', OrcidPaperSource(max_results=1000)),
       ]
    r = Researcher.objects.get(pk=pk)

    # If it is the first time we fetch this researcher
    # if r.stats is None:
    # make sure publications already known are also considered
    update_researcher_task(r, 'clustering')
    try:
        for key, source in sources:
            update_researcher_task(r, key)
            source.fetch_and_save(r)
        update_researcher_task(r, None)

    except MetadataSourceException as e:
        raise e
    finally:
        r = Researcher.objects.get(pk=pk)
        update_researcher_task(r, 'stats')
        r.update_stats()
        r.harvester = None
        update_researcher_task(r, None)


@shared_task(name='change_publisher_oa_status')
def change_publisher_oa_status(pk, status):
    publisher = Publisher.objects.get(pk=pk)
    publisher.change_oa_status(status)
    publisher.update_stats()


@shared_task(name='consolidate_paper')
@run_only_once('consolidate_paper', keys=['pk'], timeout=1*60)
def consolidate_paper(pk):
    p = None
    try:
        p = Paper.objects.get(pk=pk)
        abstract = p.abstract or ''
        for pub in p.publications:
            pub = consolidate_publication(pub)
            if pub.description and len(pub.description) > len(abstract):
                break
    except Paper.DoesNotExist:
        print "consolidate_paper: unknown paper %d" % pk


@shared_task(name='update_all_stats')
@run_only_once('refresh_stats', timeout=3*60)
def update_all_stats():
    """
    Updates the stats for every model using them
    """
    AccessStatistics.update_all_stats(PaperWorld)
    AccessStatistics.update_all_stats(Publisher)
    AccessStatistics.update_all_stats(Journal)
    AccessStatistics.update_all_stats(Institution)
    #AccessStatistics.update_all_stats(Researcher)
    #AccessStatistics.update_all_stats(Department)



@shared_task(name='update_journal_stats')
@run_only_once('refresh_journal_stats', timeout=10*60)
def update_journal_stats():
    """
    Updates statistics for journals (only visible to admins, so
    not too frequently please)
    """
    AccessStatistics.update_all_stats(Journal)


@shared_task(name='update_crossref')
@run_only_once('update_crossref', timeout=24*3600)
def update_crossref():
    """
    Updates paper metadata from Crossref
    """
    c = CrossRefAPI()
    c.fetch_and_save_new_records()

