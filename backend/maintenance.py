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

"""
This module contains functions that are not normally needed
to run the platform, but that can be useful during development,
or to cleanup various things in the database.

These functions are not integrated in the rest of the platform,
so running them involves starting a Django shell ("python manage.py shell"),
importing this module and running the function manually.
"""



from bulk_update.helper import bulk_update

from papers.models import Name
from papers.models import Paper
from papers.models import Researcher
from datetime import datetime
from elasticsearch.helpers import bulk
from elasticsearch.exceptions import ConnectionTimeout
from time import sleep
import haystack
from haystack.exceptions import SkipDocument
from haystack.constants import ID
import logging

logger = logging.getLogger('dissemin.' + __name__)

def update_index_for_model(model, batch_size=256, batches_per_commit=10, firstpk=0):
    """
    More efficient update of the search index for large models such as
    Paper

    :param batch_size: the number of instances to retrieve for each query
    :param batches_per_commit: the number of batches after which we
                    should commit to the search engine
    :param firstpk: the instance to start with.
    """
    using_backends = haystack.connection_router.for_write()
    if len(using_backends) != 1:
        raise ValueError("Don't know what search index to use")
    engine = haystack.connections[using_backends[0]]
    backend = engine.get_backend()
    index = engine.get_unified_index().get_index(model)

    qs = model.objects.order_by('pk')
    lastpk_object = list(model.objects.order_by('-pk')[:1])

    if not lastpk_object: # No object in the model
        return

    lastpk = lastpk_object[0].pk

    batch_number = 0

    # rate reporting
    indexed = 0
    starttime = datetime.utcnow()

    while firstpk < lastpk:
        batch_number += 1

        prepped_docs = []
        for obj in qs.filter(pk__gt=firstpk)[:batch_size]:
            firstpk = obj.pk

            try:
                prepped_data = index.full_prepare(obj)
                final_data = {}

                # Convert the data to make sure it's happy.
                for key, value in list(prepped_data.items()):
                    final_data[key] = backend._from_python(value)
                final_data['_id'] = final_data[ID]

                prepped_docs.append(final_data)
            except SkipDocument:
                continue

        documents_sent = False
        while not documents_sent:
            try:
                bulk(backend.conn, prepped_docs, index=backend.index_name, doc_type='modelresult')
                documents_sent = True
            except ConnectionTimeout as e:
                logger.warning(e)
                logger.info('retrying')
                sleep(30)

        indexed += len(prepped_docs)
        if batch_number % batches_per_commit == 0:
            backend.conn.indices.refresh(index=backend.index_name)

        if indexed >= 5000:
            curtime = datetime.utcnow()
            rate = int(indexed / (curtime-starttime).total_seconds())
            logger.info("%d obj/s, %d / %d" % (rate,firstpk,lastpk))
            starttime = curtime
            indexed = 0

def enumerate_large_qs(queryset, key='pk', batch_size=256, lastval=None):
    """
    Enumerates a large queryset (milions of rows) efficiently
    """
    found = True

    while found:
        sliced = queryset.order_by(key)
        if lastval is not None:
            sliced = sliced.filter(**{key+'__gt':lastval})
        logger.info(lastval)
        sliced = sliced[:batch_size]

        found = False
        for elem in sliced:
            found = True
            lastval = getattr(elem, key)
            yield elem

def update_availability():
    for paper in enumerate_large_qs(Paper.objects.filter(oa_status='UNK')):
        paper.update_availability()
        if paper.oa_status != 'UNK':
            paper.update_index()

def cleanup_researchers():
    """
    Deletes all the researchers who have not authored any paper.
    """
    deleted_count = 0
    for p in Researcher.objects.all():
        nb_papers = p.papers.count()
        if not nb_papers:
            deleted_count += 1
            p.delete()
    logger.ingo("Deleted "+str(deleted_count)+" researchers")

def update_paper_statuses():
    """
    Should only be run if something went wrong,
    the backend is supposed to update the fields by itself
    """
    papers = Paper.objects.all()
    for p in papers:
        p.update_availability()

def cleanup_paper_researcher_ids():
    """
    Ensures that all researcher_ids in Papers link to actual researchers
    """
    researcher_ids = set(Researcher.objects.all().values_list('id', flat=True))
    bs = 1000
    curid = 0
    found = True
    while found:
        found = False
        batch = []
        for p in Paper.objects.filter(id__gt=curid).order_by('id')[:bs]:
            curid = p.id
            found = True
            modified = False
            for i, author in enumerate(p.authors_list):
                rid = author['researcher_id']
                if (rid is not None and rid not in researcher_ids):
                    p.authors_list[i]['researcher_id'] = None
                    modified = True
            if modified:
                batch.append(p)
        if batch:
            logger.info("Updating {} papers, from {}".format(len(batch), curid))
            bulk_update(batch)
        else:
            logger.info(curid)

def fix_duplicate_orcids(p):
    from collections import defaultdict
    from papers.name import most_similar_author
    counts = defaultdict(int)
    for a in p.authors:
        if a.orcid:
            counts[a.orcid] += 1

    author_name_pairs = p.author_name_pairs()
    best_indices = {}
    for orcid, count in list(counts.items()):
        if count >= 2:
            try:
                n = Name.objects.get(researcher__orcid=orcid)
                best_author = most_similar_author(n.pair, author_name_pairs)
                best_indices[best_author] = orcid
            except Name.DoesNotExist:
                logger.exception('DUPLICATE ORCID WITH NO RESEARCHER_ID')

    logger.info(best_indices)
    for idx, a in enumerate(p.authors):
        if a.orcid and counts[a.orcid] >= 2:
            if best_indices.get(idx) != a.orcid:
                # delete
                p.authors_list[idx]['orcid'] = None
                p.authors_list[idx]['researcher_id'] = None

    if best_indices:
        p.save()
        p.update_index()

def report_dubious_orcids():
    """
    Finds ORCID ids which don't match the researcher's name at all
    """
    for idx, p in enumerate(Paper.objects.all().iterator()):
        if idx % 100000 == 0:
            logger.info(idx)
        seen_orcids = set()
        for a in p.authors:
            if not a.orcid:
                continue

            bad_orcid = a.orcid in seen_orcids
            seen_orcids.add(a.orcid)
            if bad_orcid:
                logger.info('\t'.join([
                    'https://dissem.in'+p.url,
                    a.orcid,
                ])+'\n')

