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
This module defines *bare* versions of the regular models: these
are classes whose instances do not correspond to an object in the database.
They are only stored in memory. This is useful for the API, where lookups are done online,
without name ambiguity resolution.
"""

from __future__ import unicode_literals

import hashlib
import re
from urllib import quote  # for the Google Scholar and CORE link
from urllib import urlencode

from django.apps import apps
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from django.template.defaultfilters import slugify
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from papers.fingerprint import create_paper_plain_fingerprint
from papers.utils import datetime_to_date
from papers.utils import iunaccent
from papers.utils import maybe_recapitalize_title
from papers.utils import remove_diacritics
from papers.utils import remove_nones
from papers.utils import sanitize_html
from papers.utils import validate_orcid
from publishers.models import DummyPublisher
from publishers.models import OA_STATUS_CHOICES
from publishers.models import OA_STATUS_PREFERENCE

PAPER_TYPE_CHOICES = [
   ('journal-article', _('Journal article')),
   ('proceedings-article', _('Proceedings article')),
   ('book-chapter', _('Book chapter')),
   ('book', _('Book')),
   ('journal-issue', _('Journal issue')),
   ('proceedings', _('Proceedings')),
   ('reference-entry', _('Entry')),
   ('poster', _('Poster')),
   ('report', _('Report')),
   ('thesis', _('Thesis')),
   ('dataset', _('Dataset')),
   ('preprint', _('Preprint')),
   ('other', _('Other document')),
   ]

PAPER_TYPE_PREFERENCE = [x for (x, y) in PAPER_TYPE_CHOICES]

MAX_NAME_LENGTH = 256


class BareObject(object):
    """
    A Bare object contains the skeleton for a non-bare (Django model) class.
    Its fields are stored in memory only and it does not correspond to a DB entry.
    To convert a bare object to its non-bare counterpart, for instance a BareName `b`
    into a Name, use `Name.from_bare(b)`.
    """
    _bare_fields = []
    _bare_foreign_key_fields = []
    _mandatory_fields = []

    def __init__(self, *args, **kwargs):
        """
        Keyword arguments can be used to set fields of this bare object.
        """
        super(BareObject, self).__init__()
        if isinstance(self, models.Model):
            return
        for f in self._bare_fields + self._bare_foreign_key_fields:
            if not hasattr(self, f):
                self.__dict__[f] = None
        for f in self._bare_foreign_key_fields:
            if f+'_id' not in self.__dict__:
                self.__dict__[f+'_id'] = None
        for k, v in kwargs.items():
            if k in self._bare_fields:
                self.__dict__[k] = v
            elif k in self._bare_foreign_key_fields:
                self.__dict__[k] = v
                if hasattr(v, 'id'):
                    self.__dict__[k+'_id'] = v.id
                else:
                    self.__dict__[k+'_id'] = None

    @classmethod
    def from_bare(cls, bare_obj):
        """
        This creates an instance of the current class as a copy of a
        bare instance. Concretely, this copies all the fields contained
        in the bare object to an instance of the current class, which
        is expected to be a subclass of the bare object's class.
        """
        kwargs = {}
        for k, v in bare_obj.__dict__.items():
            if k in cls._bare_fields:
                kwargs[k] = v
            elif k in cls._bare_foreign_key_fields:
                kwargs[k] = v

        ist = cls(**kwargs)
        return ist

    def breadcrumbs(self):
        """
        Breadcrumbs of bare objects are empty by default.
        """
        return [(unicode(self), '#')]

    def check_mandatory_fields(self):
        """
        Raises `ValueError` if any field is missing.
        The list of mandatory fields for the class should be stored in `_mandatory_fields`.
        """
        for field in self._mandatory_fields:
            if not self.__dict__.get(field):
                raise ValueError('No %s provided to create a %s.' %
                                 (field, self.__class__.__name__))


class BarePaper(BareObject):
    """
    This class is the bare analogue to :class:`Paper`. Its authors are
    lists of :class:`BareName`, and its publications and OAI records are also bare.
    """
    _bare_fields = [
        #! The title of the paper
        'title',
        #! The fingerprint (robust version of the title, authors and year)
        'fingerprint',
        #! The publication date
        'pubdate',
        #! The document type
        'doctype',
        #! The OA status
        'oa_status',
        #! The url where we think the full text is available
        'pdf_url',
        #! Visibility
        'visible',
    ]

    _mandatory_fields = [
        'title',
        'pubdate',
        'fingerprint',
    ]

    # Value above which we consider a paper to have too many authors to be
    # displayed. See BarePaper.has_many_authors
    MAX_DISPLAYED_AUTHORS = 15

    @property
    def slug(self):
        return slugify(self.title)

    # Creation

    def __init__(self, *args, **kwargs):
        super(BarePaper, self).__init__(*args, **kwargs)
        #! The authors: a list of :class:`BareName`
        self.bare_authors = []
        #! The OAI records associated with this paper: dict of :class:`BareOaiRecord` indexed by their identifiers
        self.bare_oairecords = {}
        #! If there are lots of authors, how many are we hiding?
        self.nb_remaining_authors = None
        #! This property is used in Paper to save SQL requests when
        # adding OaiRecords
        self.just_created = False

    @classmethod
    def from_bare(cls, bare_obj):
        """
        Creates an instance of this class from a :class:`BarePaper`.
        """
        bare_obj.update_availability()
        bare_obj.fingerprint = bare_obj.new_fingerprint()
        ist = super(BarePaper, cls).from_bare(bare_obj)
        for idx, a in enumerate(bare_obj.authors):
            ist.add_author(a, position=idx)
        ist.save()
        ist.just_created = True
        for r in bare_obj.oairecords:
            ist.add_oairecord(r)
        return ist

    @classmethod
    def create(cls, title, author_names, pubdate, visible=True,
               affiliations=None, orcids=None):
        """
        Creates a (bare) paper. To save it to the database, we
        need to run the clustering algorithm to resolve Researchers for the authors,
        using `from_bare` from the (non-bare) :class:`Paper` subclass..

        :param title: The title of the paper (as a string). If it is too long for the database,
                      ValueError is raised.
        :param author_names: The ordered list of author names, as Name objects.
        :param pubdate: The publication date, as a python date object
        :param visible: The visibility of the paper if it is created. If another paper
                    exists, the visibility will be set to the maximum of the two possible
                    visibilities.
        :param affiliations: A list of (possibly None) affiliations for the authors. It has to
                    have the same length as the list of author names.
        :param orcids: same as affiliations, but for ORCID ids.
        """
        if not title or not author_names or not pubdate:
            raise ValueError(
                "A title, pubdate and authors have to be provided to create a paper.")

        if affiliations is not None and len(author_names) != len(affiliations):
            raise ValueError(
                "The number of affiliations and authors have to be equal.")
        if orcids is not None and len(author_names) != len(orcids):
            raise ValueError(
                "The number of ORCIDs (or Nones) and authors have to be equal.")
        if not isinstance(visible, bool):
            raise ValueError("Invalid paper visibility: %s" % unicode(visible))

        title = sanitize_html(title)
        title = maybe_recapitalize_title(title)

        p = cls()
        p.title = title
        p.pubdate = pubdate  # pubdate will be checked in fingerprint computation
        p.visible = visible
        for idx, n in enumerate(author_names):
            a = BareAuthor()
            a.name = n
            if affiliations is not None:
                a.affiliation = affiliations[idx]
            if orcids is not None:
                orcid = validate_orcid(orcids[idx])
                if orcid:
                    a.orcid = orcid
            p.add_author(a, position=idx)

        p.fingerprint = p.new_fingerprint()

        return p

    ### Properties to be reimplemented by non-bare Paper ###
    @property
    def authors(self):
        """
        The list of authors. They are bare in :class:`BarePaper`. In
        other implementations, they can be arbitrary iterables of subclasses
        of :class:`BareAuthor`.
        They are sorted in their natural order on paper.
        """
        return self.bare_authors

    @property
    def oairecords(self):
        """
        The list of OAI records associated with this paper. It can
        be arbitrary iterables of subclasses of :class:`BareOaiRecord`.
        """
        return self.bare_oairecords.values()

    def add_author(self, author, position=None):
        """
        Adds a new author to the paper, at the end of the list.

        :param position: if provided, set the author to the given position.

        :returns: the :class:`BareAuthor` that was added (it can differ in subclasses)
        """
        if position is not None:
            if not (position >= 0 and position <= len(self.bare_authors)):
                raise ValueError("Invalid author position '%s' of %d" %
                                 (str(position), len(self.bare_authors)))
            self.bare_authors.insert(position, author)
        else:
            self.bare_authors.append(author)
        return author

    def set_researcher(self, position, researcher_id):
        """
        Sets the researcher_id for the author at the given position
        (0-indexed)
        """
        if position < 0 or position > len(self.authors_list):
            raise ValueError('Invalid position provided')
        self.bare_authors[position].researcher_id = researcher_id

    def add_oairecord(self, oairecord):
        """
        Adds a new OAI record to the paper

        :returns: the :class:`BareOaiRecord` that was added (it can differ in subclasses)
        """
        oairecord.check_mandatory_fields()
        self.bare_oairecords[oairecord.identifier] = oairecord
        # update the publication date
        self.pubdate = datetime_to_date(self.pubdate)
        if oairecord.pubdate:
            new_pubdate = datetime_to_date(oairecord.pubdate)
            if new_pubdate > self.pubdate:
                self.pubdate = new_pubdate

        self.just_created = False
        return oairecord

    ### Generic properties that should not need to be reimplemented ###
    @property
    def year(self):
        """
        Year of publication of the paper.
        """
        return self.pubdate.year

    # OAI records -----------------

    @cached_property
    def sorted_oai_records(self):
        """
        OAI records sorted by decreasing order of priority
        (lower priority means poorer overall quality of the source).
        """
        # Ordered in Python because the list of records is typically quite
        # small (less than 10 items)
        return sorted(self.oairecords, key=lambda r: -r.priority)

    @cached_property
    def prioritary_oai_records(self):
        """
        OAI records from custom sources we trust (positive priority)
        """
        # Filtered in Python because the list of records is typically quite
        # small (less than 10 items)
        return [r for r in self.sorted_oai_records if r.priority > 0]

    @property
    def unique_prioritary_oai_records(self):
        """
        OAI records from sources we trust, with unique source.
        """
        seen_sources = set()
        for record in self.prioritary_oai_records:
            if record.source_id not in seen_sources:
                seen_sources.add(record.source_id)
                yield record

    # Authors ------------------------

    def author_names(self):
        """
        The list of Name instances of the authors
        """
        return [a.name for a in self.authors]

    def affiliations(self):
        """
        The list of affiliations of all authors
        """
        return [a.affiliation for a in self.authors]

    def orcids(self):
        """
        The list of ORCIDs of all authors
        """
        return [a.orcid for a in self.authors]

    def bare_author_names(self):
        """
        The list of name pairs (first,last) of the authors
        """
        return [(name.first, name.last) for name in self.author_names()]

    @property
    def author_count(self):
        """
        Number of authors.
        """
        return len(self.authors)

    @property
    def has_many_authors(self):
        """
        When the paper has more than some arbitrary number of authors.
        """
        return self.author_count > self.MAX_DISPLAYED_AUTHORS

    @cached_property
    def interesting_authors(self):
        """
        The list of authors to display when the complete list is too long.
        """
        # TODO: Better selection
        lst = self.authors[:self.MAX_DISPLAYED_AUTHORS]
        self.nb_remaining_authors = self.author_count - len(lst)
        return lst

    def displayed_authors(self):
        """
        Returns the full list of authors if there are not too many of them,
        otherwise returns only the interesting_authors()
        """
        if self.has_many_authors:
            return self.interesting_authors
        else:
            return self.authors

    def check_authors(self):
        """
        Check the sanity of authors
        (for now, only that the list is non-empty)
        """
        if not self.authors:
            raise ValueError("Empty authors list")
        # TODO more checks here?

    # Publications ---------------------------------------------

    @property
    def publications(self):
        """
        The OAI records with publication metadata (i.e. journal title and
        publisher name).
        These records can potentially be associated with publisher policies.
        """
        res = []
        # we don't yield because some functions actually do len( ) on the
        # output of this method…
        for r in self.oairecords:
            if r.has_publication_metadata():
                res.append(r)
        return res

    def first_publications(self):
        """
        The list of the 3 first OAI records with publication metadata
        associated with this paper (in most cases, that should return *all*
        such records, but in some nasty cases many publications end up
        merged, and it is not very elegant to show all of them
        to the users).
        """
        return list(self.publications)[:3]

    def publications_with_unique_publisher(self):
        """
        Iterable of publications where subsequent publications with
        the same publisher are removed.
        """
        seen_publishers = set()
        for publication in self.publications:
            if publication.publisher_id and publication.publisher_id not in seen_publishers:
                seen_publishers.add(publication.publisher_id)
                yield publication
            elif publication.publisher_name not in seen_publishers:
                seen_publishers.add(publication.publisher_name)
                yield publication

    def publisher(self):
        """
        Returns the first publisher we can find for this paper, otherwise
        a :class:`DummyPublisher`
        """
        for publication in self.publications:
            return publication.publisher_or_default()
        return DummyPublisher()

    # Fingerprint -----------------------------------------------
    def plain_fingerprint(self, verbose=False):
        """
        Debugging function to display the plain fingerprint
        """
        fp = create_paper_plain_fingerprint(
            self.title, self.bare_author_names(), self.year, self.pubdate)
        if verbose:
            print fp
        return fp

    def new_fingerprint(self, verbose=False):
        """
        The fingerprint of the paper, taking into account the changes
        that may have occured since the last computation of the fingerprint.
        This does not update the `fingerprint` field, just computes its candidate value.
        """
        buf = self.plain_fingerprint(verbose)
        m = hashlib.md5()
        m.update(buf)
        return m.hexdigest()

    # Abstract -------------------------------------------------
    @cached_property
    def abstract(self):
        best_abstract = ''
        for rec in self.oairecords:
            if rec.description and len(rec.description) > len(best_abstract):
                best_abstract = rec.description
        return best_abstract

    # Updates ---------------------------------------------------
    def update_availability(self, cached_oairecords=None):
        """
        Updates the :class:`BarePaper`'s own `pdf_url` field
        based on its sources (:class:`BareOaiRecord`).

        This uses a non-trivial logic, hence it is useful to keep this result cached
        in the database row.

        :param cached_oairecords: the list of OaiRecords if we already have it
                           from somewhere (otherwise it is fetched)
        """
        if cached_oairecords is None:
            cached_oairecords = []
        records = list(cached_oairecords or self.oairecords)
        records = sorted(records, key=(lambda r: -r.priority))

        self.pdf_url = None
        oa_idx = len(OA_STATUS_PREFERENCE)-1
        type_idx = len(PAPER_TYPE_PREFERENCE)-1
        source_found = False

        if self.doctype in PAPER_TYPE_PREFERENCE:
            type_idx = PAPER_TYPE_PREFERENCE.index(self.doctype)

        for rec in records:
            if rec.has_publication_metadata():
                # OA status
                cur_status = rec.oa_status()
                try:
                    idx = OA_STATUS_PREFERENCE.index(cur_status)
                except ValueError:
                    idx = len(OA_STATUS_PREFERENCE)
                oa_idx = min(idx, oa_idx)
                if OA_STATUS_CHOICES[oa_idx][0] == 'OA':
                    self.pdf_url = rec.pdf_url or rec.splash_url
            else:
                if not self.pdf_url and rec.pdf_url:
                    self.pdf_url = rec.pdf_url

            # Pub type
            cur_type = rec.pubtype
            try:
                idx = PAPER_TYPE_PREFERENCE.index(cur_type)
            except ValueError:
                idx = len(PAPER_TYPE_PREFERENCE)
            type_idx = min(idx, type_idx)

            source_found = True

        self.oa_status = OA_STATUS_CHOICES[oa_idx][0]

        # If this paper is not associated with any source, do not display it
        # This happens when creating the associated OaiRecord
        # failed due to some missing information.
        if not source_found:
            self.visible = False

        self.doctype = PAPER_TYPE_PREFERENCE[type_idx]

    def update_visible(self):
        """
        Updates the visibility of the paper. Only papers with at least
        one source should be visible.
        """
        self.visible = not self.is_orphan()

    # Other representations ------------------------------------------
    def __unicode__(self):
        """
        Title of the paper
        """
        return self.title

    def json(self):
        """
        JSON representation of the paper, for dataset dumping purposes
        """
        return remove_nones({
            'title': self.title,
            'type': self.doctype,
            'date': self.pubdate.isoformat(),
            'authors': [a.json() for a in self.authors],
            'records': [r.json() for r in self.oairecords],
            'pdf_url': self.pdf_url,
            'classification': self.oa_status,
            })

    def google_scholar_link(self):
        """
        Link to search for the paper in Google Scholar
        """
        return 'http://scholar.google.com/scholar?'+urlencode({'q': remove_diacritics(self.title)})

    def core_link(self):
        """
        Link to search for the paper in CORE
        """
        return 'http://core.ac.uk/search/'+quote(remove_diacritics(self.title))

    def is_orphan(self):
        """
        When no OAI record is associated with this paper.
        """
        return (len(self.oairecords) == 0)

    def citation(self):
        """
        A short citation-like representation of the paper. E.g. Joyal and Street, 1992
        """
        result = ''
        if self.author_count == 1:
            result = self.authors[0].name.last
        elif self.author_count == 2:
            result = "%s and %s" % (
                self.authors[0].name.last,
                self.authors[1].name.last)
        else:
            result = "%s et al." % (
                self.authors[0].name.last)
        result += ', %d' % self.year
        return result


class BareAuthor(BareObject):
    """
    The base class for the author of a paper.
    This holds the name of the author, its position in the authors list,
    and its possible affiliations.
    """
    _bare_fields = [
        'affiliation',
        'orcid',
        'researcher_id',
    ]
    _bare_foreign_key_fields = [
        'name',
    ]
    _mandatory_fields = [
        'name',
    ]

    @cached_property
    def _researcher_model(self):
        return apps.get_app_config('papers').get_model('Researcher')

    @cached_property
    def researcher(self):
        """
        Returns the :class:`Researcher` object associated with
        this author (if any)
        """
        if self.researcher_id:
            return self._researcher_model.objects.get(id=self.researcher_id)

    @property
    def is_known(self):
        """
        An author is "known" when it is linked to a known researcher.
        """
        return self.researcher != None

    def update_name_variants_if_needed(self, default_confidence=0.1):
        """
        Ensure that an author associated with an ORCID has a name
        that is the variant of the researcher with that ORCID
        """
        orcid = self.orcid
        if orcid:
            try:
                r = self._researcher_model.objects.get(orcid=orcid)
                NameVariant = apps.get_app_config(
                    'papers').get_model('NameVariant')
                NameVariant.objects.get_or_create(
                        researcher=r,
                        name=self.name,
                        defaults={'confidence': default_confidence})
            except ObjectDoesNotExist:
                pass

    # Representations -------------------------------
    def __unicode__(self):
        """
        Unicode representation: name of the author
        """
        return unicode(self.name)

    def serialize(self):
        """
        JSON representation for storage in a JSON field
        (internal, not to be used as the output of the API)
        """
        return {
            'name': self.name.serialize(),
            'orcid': self.orcid,
            'affiliation': self.affiliation,
            'researcher_id': self.researcher_id,
            }

    @classmethod
    def deserialize(cls, rep):
        """
        Creates an Author object out of a serialized representation.
        """
        name = BareName.deserialize(rep['name'])
        inst = cls(
            affiliation=rep.get('affiliation'),
            orcid=rep.get('orcid'),
            name=name,
            researcher_id=rep.get('researcher_id'),
            )
        return inst

    def json(self):
        """
        JSON representation of the author for dataset dumping purposes,
        or for the public API.
        """
        orcid_id = self.orcid
        affiliation = None
        if not orcid_id and self.affiliation:
            affiliation = self.affiliation
        return remove_nones({
                'name': self.name.json(),
                'affiliation': affiliation,
                'orcid': orcid_id,
                })


class BareName(BareObject):
    _bare_fields = [
        'first',
        'last',
        'full',
    ]

    _mandatory_fields = [
        'last',
        # first name can be empty, full is generated from first and last
    ]

    @classmethod
    def create_bare(cls, first, last):
        """
        Same as `create`, provided for uniformity among bare classes.
        """
        return cls.create(first, last)

    @property
    def is_known(self):
        """
        Does this name belong to at least one known researcher?
        """
        return True

    @classmethod
    def create(cls, first, last):
        """
        Creates an instance of the Name object without saving it.
        Useful for name lookups where we are not sure we want to
        keep the name in the model.
        """
        instance = cls()
        instance.first = sanitize_html(first[:MAX_NAME_LENGTH].strip())
        instance.last = sanitize_html(last[:MAX_NAME_LENGTH].strip())
        instance.full = iunaccent(instance.first+' '+instance.last)
        return instance

    def __unicode__(self):
        """
        Unicode representation: first name followed by last name
        """
        return '%s %s' % (self.first, self.last)

    def first_letter(self):
        """
        First letter of the last name, for sorting purposes
        """
        if self.last:
            return self.last[0]
        elif self.first:
            return self.first[0]

    def serialize(self):
        """
        JSON representation for internal storage purposes
        """
        return {
            'first': self.first,
            'last': self.last,
            'full': self.full,
            }

    @property
    def pair(self):
        return (self.first, self.last)

    @classmethod
    def deserialize(cls, rep):
        """
        Reconstruct an object based on its serialized representation
        """
        inst = cls(
            first=rep['first'],
            last=rep['last'],
            full=rep['full'],
            )
        return inst

    def json(self):
        """
        Returns a JSON representation of the name (for external APIs)
        """
        return {
                'first': self.first,
                'last': self.last,
               }

    def __repr__(self):
        return "<BareName: %s, %s>" % (unicode(self.first),
                                       unicode(self.last))


class BareOaiRecord(BareObject):
    _bare_foreign_key_fields = [
        'source',  # expected to be an OaiSource
        'journal',  # expected to be a Journal
        'publisher',  # expected to be a Publisher
    ]

    _bare_fields = [
        'identifier',
        'splash_url',
        'pdf_url',
        'description',
        'keywords',
        'contributors',
        'pubtype',
        'priority',
        'journal_title',
        'container',
        'publisher_name',
        'issue',
        'volume',
        'pages',
        'pubdate',
        'doi',
    ]

    _mandatory_fields = [
        'identifier',
        'splash_url',
        'source',
    ]

    def __init__(self, *args, **kwargs):
        super(BareOaiRecord, self).__init__(*args, **kwargs)
        if not isinstance(self, models.Model) and self.source:
            self.priority = self.source.priority

    def update_priority(self):
        self.priority = self.source.priority

    def oa_status(self):
        """
        Policy of the publisher for this publication
       """
        if self.pdf_url:
            return 'OA'
        elif self.publisher:
            if self.publisher.oa_status == 'OA' and self.doi:
                self.pdf_url = 'https://doi.org/'+self.doi
            return self.publisher.oa_status
        else:
            return 'UNK'

    def full_journal_title(self):
        """
        The full title of the journal, otherwise the title present
        in CrossRef's metadata, which might be shorter.
        """
        if self.journal:
            return self.journal.title
        else:
            return self.journal_title

    def publisher_or_default(self):
        """
        Returns the publisher. If the publisher is unknown,
        returns an instance of :class:`DummyPublisher`.
        """
        if self.publisher_id:
            return self.publisher
        if self.publisher_name:
            return DummyPublisher(self.publisher_name)
        return DummyPublisher()

    def has_publication_metadata(self):
        """
        Does this record tell where the paper is published?
        If so we can use it to look up the policy in RoMEO.
        """
        return bool(self.journal_title and self.publisher_name)

    def source_or_publisher(self):
        """
        Returns the name of the source to display.
        If the record comes from a repository that we index
        directly via OAI-PMH, we return the name of the source.
        If the record has a publisher name, we return the
        publisher name.
        """
        if self.publisher:
            return self.publisher.name
        return self.source.name

    def cleanup_description(self):
        """
        Removes clutter frequently included in abstracts.
        Note that this does not save the object (being
        a method of BareOaiRecord).
        """
        if not self.description:
            return
        abstract_re = re.compile(
            r'^\s*(abstract|international audience)\s*(\.|:|;)\s',
            flags=re.IGNORECASE)
        self.description = abstract_re.sub('', self.description)

    def __unicode__(self):
        """
        The record's identifier
        """
        return self.identifier

    def json(self):
        """
        Dumps the OAI record as a JSON object (for dataset dumping purposes)
        """
        result = {}
        if self.publisher:
            result['policy'] = self.publisher.json()
        if self.journal:
            result['issn'] = self.journal.issn
        result.update({
                'source': self.source.identifier,
                'identifier': self.identifier,
                'splash_url': self.splash_url,
                'pdf_url': self.pdf_url,
                'doi': self.doi,
                'abstract': self.description,
                'keywords': self.keywords,
                'contributors': self.contributors,
                'type': self.pubtype,
                'publisher': self.publisher_name,
                'journal': self.full_journal_title(),
                'container': self.container,
                'issue': self.issue,
                'volume': self.volume,
                'pages': self.pages,
                })
        return remove_nones(result)
