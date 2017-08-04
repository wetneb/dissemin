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

from caching.base import CachingManager
from caching.base import CachingMixin
from deposit.registry import protocol_registry
from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.utils.translation import ugettext_lazy as _
from papers.models import OaiSource
from papers.models import Paper
from papers.models import OaiRecord
from papers.models import UPLOAD_TYPE_CHOICES
from upload.models import UploadedPDF

DEPOSIT_STATUS_CHOICES = [
   ('failed', _('Failed')), # we failed to deposit the paper
   ('faked', _('Faked')), # the deposit was faked (for tests)
   ('pending', _('Pending publication')), # the deposit has been
    # submitted but is not publicly visible yet
   ('published', _('Published')), # the deposit is visible on the repo
   ('refused', _('Refused by the repository')),
   ('deleted', _('Deleted')), # deleted by the repository
   ]

class RepositoryManager(CachingManager):
    pass

class Repository(models.Model, CachingMixin):
    """
    This model stores the parameters for a particular repository.

    The `name`, `description`, `url` and `logo` fields are used in the
    user interface to present the repository.

    The `protocol` field should contain the name of a subclass of
    :class:`~deposit.protocol.RepositoryProtocol` which implements the API supported
    by the repository.
    Note that this subclass needs to be registered in the :data:`~deposit.registry.protocol_registry`
    in order to be available at runtime.

    The `api_key`, `username`, `password` and `endpoint` are parameters
    used by the protocol implementation to perform the deposit.

    """
    objects = RepositoryManager()

    #: Name
    name = models.CharField(max_length=64)
    #: Description
    description = models.TextField()
    #: URL of the homepage (ex: http://arxiv.org/ )
    url = models.URLField(max_length=256, null=True, blank=True)
    #: Logo
    logo = models.ImageField(upload_to='repository_logos/')

    #: The identifier of the interface (protocol) used for that repository
    protocol = models.CharField(max_length=32)
    #: The source with which the OaiRecords associated with the deposits are created
    oaisource = models.ForeignKey(OaiSource)

    #: The identifier of the account under which papers should be deposited
    username = models.CharField(max_length=64, null=True, blank=True)
    #: The password for that account
    password = models.CharField(max_length=128, null=True, blank=True)
    #: An API key required by the protocol
    api_key = models.CharField(max_length=256, null=True, blank=True)
    #: The API's endpoint
    endpoint = models.CharField(max_length=256, null=True, blank=True)

    #: Setting this to false forbids any deposit in this repository
    enabled = models.BooleanField(default=True)

    def get_implementation(self):
        """
        Creates an instance of the class corresponding to the protocol identifier,
        bound with this repository. If the class cannot be found
        in the :data:`~deposit.registry.protocol_registry`, `None` is returned.

        :returns: the class corresponding to the value of the `protocol` field.
        """
        cls = protocol_registry.get(self.protocol)
        if cls is None:
            print "Warning: protocol not found: "+unicode(self.protocol)
            return
        return cls(self)

    def protocol_for_deposit(self, paper, user):
        """
        Returns an instance of the protocol initialized for the given
        paper and user, if initialization succeeded.

        :returns: an instance of the protocol implementation, or `None`
            if the instance failed to initialize with the given paper and user.
        """
        if not self.enabled:
            return
        instance = self.get_implementation()
        if instance is None:
            return
        if instance.init_deposit(paper, user):
            return instance

    def __unicode__(self):
        """
        The unicode representation is just the name of the repository.
        """
        return self.name

    class Meta:
        verbose_name_plural = 'Repositories'


class DepositRecord(models.Model):
    """
    This model stores the results of a deposit initiated by the user,
    regardless of its success. Protocol implementers should not
    have to deal with this model directly, their interfaces should
    only manipulate :class:`~deposit.protocol.DepositResult` objects
    and :class:`~deposit.protocol.DepositError` exceptions, depending
    on the success of the deposit.
    """
    paper = models.ForeignKey(Paper)
    user = models.ForeignKey(User)

    repository = models.ForeignKey(Repository)

    request = models.TextField(null=True, blank=True)
    identifier = models.CharField(max_length=512, null=True, blank=True)
    oairecord = models.ForeignKey(OaiRecord, null=True, blank=True)
    date = models.DateTimeField(auto_now=True)  # deposit date
    upload_type = models.CharField(max_length=64,choices=UPLOAD_TYPE_CHOICES)
    status = models.CharField(max_length=64,choices=DEPOSIT_STATUS_CHOICES)
    additional_info = JSONField(null=True, blank=True)

    file = models.ForeignKey(UploadedPDF)

    class Meta:
        db_table = 'papers_depositrecord'

    def __unicode__(self):
        if self.identifier:
            return self.identifier
        else:
            return unicode(_('Deposit'))

    def __repr__(self):
        return '<DepositRecord %s>' % unicode(self.identifier)


class DepositPreferences(models.Model):
    """
    This is an abstract base model to be subclassed
    by repositories. It stores the preferences one user
    might have concerning a particular repository, such
    as default affiliation for HAL, default license, or
    things we want to fill in automatically for them.
    """
    class Meta:
        abstract = True

    #: The user for which these preferences are stored
    user = models.ForeignKey(User)
    #: The repository for which these preferences apply
    repository = models.ForeignKey(Repository)

    @classmethod
    def get_form_class(self):
        """
        This method should be reimplemented to return
        the form class to edit these deposit preferences.
        This is expected to be a ModelForm that get_form
        will be able to initialize with values from an
        existing instance.
        """
        raise NotImplementedError()

    def get_form(self):
        """
        This method should return the
        """
        raise NotImplementedError()


    def __repr__(self):
        return '<DepositPreferences, user %s, repo %s>' %(
                    unicode(self.user), unicode(self.repository))

class UserPreferences(models.Model):
    """
    Stores the user's global preferences,
    not the ones specific to a particular repository.
    """
    user = models.OneToOneField(User)
    # Email address
    email = models.EmailField(max_length=512, null=True, blank=True,
       help_text=_(
        'We will use this email address to notify you when your deposits are accepted.'
    ))
    # The preferred repository, set by the user
    preferred_repository = models.ForeignKey(Repository,
        null=True, blank=True,
        related_name='preferred_by',
        help_text=_('This repository will be used by default for your deposits.'))
    # The last repository used by this user
    last_repository = models.ForeignKey(Repository,
        null=True, blank=True,
        related_name='last_used_by')

    @classmethod
    def get_by_user(cls, user):
        """
        Returns a UserPreferences instance for a particular user
        """
        userprefs, _ = cls.objects.get_or_create(user=user)
        return userprefs

