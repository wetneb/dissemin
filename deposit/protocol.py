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




import traceback
import logging

from itertools import chain

from django.conf import settings
from django.utils.functional import cached_property
from django.utils.translation import ugettext as _

from deposit.forms import BaseMetadataForm
from deposit.models import DEPOSIT_STATUS_CHOICES
from deposit.models import LicenseChooser
from deposit.utils import MetadataConverter
from papers.baremodels import BareOaiRecord
from papers.models import OaiRecord

logger = logging.getLogger('dissemin.' + __name__)


class DepositError(Exception):
    """
    The exception to raise when something wrong happens
    during the deposition process
    """
    pass

class DepositResult(object):
    """
    Small object containing the result of a deposition process.
    This object will be stored in two rows in the database:
    in a BareOaiRecord and in a DepositRecord.

    status should be one of DEPOSIT_STATUS_CHOICES
    """

    def __init__(self, identifier=None, splash_url=None, pdf_url=None, logs=None, status='published', license = None, embargo_date=None, message=None):
        self.identifier = identifier
        self.splash_url = splash_url
        self.pdf_url = pdf_url
        self.logs = logs
        if status not in [x[0] for x in DEPOSIT_STATUS_CHOICES]:
            raise ValueError('invalid status '+str(status))
        self.status = status
        self.message = message
        self.license = None
        self.oairecord = None
        self.embargo_date = None
        self.additional_info = []

class RepositoryProtocolMeta(type):
    """
    Metaclass for RepositoryProtocol class. This class is used to provice __str__ for the protocol classes (not the objects).
    The inhterianted classes of RepositoryProtocol inherit this class.
    """

    def __repr__(cls):
        """
        We pass the class again, so that we later need no classmethod
        """
        return cls.__repr__(cls)

    def __str__(cls):
        """
        We pass the class again, so that we later need no classmethod
        """
        return cls.__str__(cls)

class RepositoryProtocol(object, metaclass = RepositoryProtocolMeta):
    """
    The protocol for a repository where papers can be deposited.
    Actual implementations should inherit from this class.
    """

    #. The class of the form for the deposit
    form_class = BaseMetadataForm

    #: The model for the user preferences
    #: (set to None if no preferences can be set).
    preferences_model = None

    #: The class of the form to edit the user preferences
    preferences_form_class = None

    def __init__(self, repository, **kwargs):
        self.repository = repository
        self._logs = ''
        self.paper = None
        self.user = None
    
    def __repr__(self):
        """
        Return the class name if no other value is set.
        """
        return self.__class__.__name__
    
    def __str__(self):
        """
        Return the class name if no other value is set.
        """
        return self.__class__.__name__

    def protocol_identifier(self):
        """
        Returns an identifier for the protocol.
        """
        return type(self).__name__

    def init_deposit(self, paper, user):
        """
        Called when a user starts considering depositing a paper to a repository.

        :param paper: The paper to be deposited.
        :param user: The user submitting the deposit.
        :returns: a boolean indicating if the repository can be used in this case.
        """
        self.paper = paper
        self.user = user
        self._logs = ''
        return True

    # Metadata helpers

    @cached_property
    def metadata(self):
        """
        Gives access to a dict of the metadata from the paper and its OaiRecords.
        """
        prefered_records = self._get_prefered_records()
        mc = MetadataConverter(self.paper, prefered_records)
        return mc


    def _get_prefered_records(self):
        """
        Returns the prefered records, that is CrossRef, then BASE
        """
        crossref = OaiRecord.objects.filter(
            about=self.paper,
            source__identifier='crossref',
        )
        base = OaiRecord.objects.filter(
            about=self.paper,
            source__identifier='base'
        )
        return list(chain(crossref, base))


    @staticmethod
    def _add_embargo_date_to_deposit_result(deposit_result, form):
        """
        If an embargo date does exist, add it to the deposit record
        :param deposit_result: DepositResult
        :param form: valid Form
        :returns: DepositResult
        """
        deposit_result.embargo_date = form.cleaned_data.get('embargo', None)

        return deposit_result


    @staticmethod
    def _add_license_to_deposit_result(deposit_result, form):
        """
        If a license does exist, add it to the deposit record
        :param deposit_result: DepositResult
        :param form: valid Form
        :returns: DepositResult
        """
        lc = form.cleaned_data.get('license', None)
        if lc:
            deposit_result.license = lc.license
        return deposit_result


    ### Deposit form ###
    # This section defines the form the user sees when
    # depositing a paper.

    def _get_ddcs(self):
        """
        Returns the queryset of related DDC classes of repository or ``None``
        :returns: queryset of DDC or ``None``
        """

        ddcs = self.repository.ddc.all()
        if ddcs:
            return ddcs
        else:
            return None

    def _get_licenses(self):
        """
        Returns the queryset of related licenses or the repository or ``None``.
        :returns: queryset of licenses or ``None``
        """

        licenses = LicenseChooser.objects.by_repository(self.repository)
        if licenses:
            return licenses
        else:
            return None

    def get_form_initial_data(self, **kwargs):
        """
        Returns the form's initial values.
        """

        licenses = kwargs.get('licenses', None)

        initial = {
            'paper_id' : self.paper.id,
        }
        
        if licenses:
            defaults = 0
            for license in reversed(licenses):
                if license.default == True:
                    initial['license'] = license
                    defaults += 1
            if defaults == 0:
                logger.warning('No default license set for repository %s' % self.repository)
                initial['license'] = licenses.first()
            elif defaults == 2:
                logger.warning('More than one default license set for repository %s' % self.repository)

        return initial


    def _get_form_settings(self):
        """
        This creates the form settings. It returns a dictionary that kann be passed as kwargs to the forms __init__. This is used to enable or disable fields and/or fill them with data
        :returns: Dictionary with form settings
        """
        form_settings = {
            'abstract_required' : self.repository.abstract_required,
            'ddcs' : self._get_ddcs(),
            'embargo' : self.repository.embargo,
            'licenses' : self._get_licenses(),
        }
        return form_settings


    def get_form(self):
        """
        Returns the form where the user will be able to give additional metadata.
        It is prefilled with the initial data from `get_form_initial_data`
        """

        form_settings = self._get_form_settings()

        initial = self.get_form_initial_data(licenses=form_settings.get('licenses'))

        return self.form_class(**form_settings, initial=initial)

    def get_bound_form(self, data):
        """
        Returns a bound version of the form, with the given data.
        Here, data is expected to come from a POST request generated by
        the user, ready for validation.
        """
        form_settings = self._get_form_settings()

        return self.form_class(**form_settings, data=data)

    def submit_deposit(self, pdf, form, dry_run=False):
        """
        Submit a paper to the repository.
        This is expected to raise DepositError if something goes wrong.

        :param pdf: Filename to the PDF file to submit
        :param form: The form returned by get_form and completed by the user.
        :param dry_run: if True, should
        :returns: a DepositResult object.
        """
        raise NotImplementedError(
            'submit_deposit should be implemented in the RepositoryInterface instance.')

    def refresh_deposit_status(self):
        """
        This function is meant to update deposit status. Reimplement the updating as required, by do the following:
        1. Call this function with super()
        2. Fetch all DepositRecords for the repository
        3. Update their status and the corresponding OaiRecords
        4. Save them
        5. Update availability and update index
        """
        pass

    def submit_deposit_wrapper(self, *args, **kwargs):
        """
        Wrapper of the submit_deposit method (that should not need to be
        reimplemented). It catches DepositErrors raised in the deposit process
        and adds the logs to its return value.
        """
        try:
            # Small hack to get notifications
            name = getattr(self.user, 'name', None)
            first_name = getattr(self.user, 'first_name', None)
            last_name = getattr(self.user, 'last_name', None)
            if first_name and last_name:
                name = '%s %s' % (first_name,last_name)
            notification_payload = {
                    'name':str(name),
                    'repo':self.repository.name,
                    'paperurl':self.paper.url,
                }

            result = self.submit_deposit(*args, **kwargs)
            result.logs = self._logs

            # Create the corresponding OAI record
            if result.splash_url:
                rec = BareOaiRecord(
                        source=self.repository.oaisource,
                        identifier=('deposition:%d:%s' %
                                    (self.repository.id, str(result.identifier))),
                        splash_url=result.splash_url,
                        pdf_url=result.pdf_url)
                result.oairecord = self.paper.add_oairecord(rec)

            settings.DEPOSIT_NOTIFICATION_CALLBACK(notification_payload)

            # In case that the paper is on user todo list, remove it
            # If it's not on the list, nothing happens here, since m2m field
            self.paper.todolist.remove(self.user)

            return result
        except DepositError as e:
            self.log('Message: '+e.args[0])
            notification_payload['paperurl'] += ' '+e.args[0]
            settings.DEPOSIT_NOTIFICATION_CALLBACK(notification_payload)
            return DepositResult(logs=self._logs, status='failed', message=e.args[0])
        except Exception as e:
            self.log("Caught exception:")
            self.log(str(type(e))+': '+str(e)+'')
            self.log(traceback.format_exc())
            return DepositResult(logs=self._logs, status='failed', message=_('Failed to connect to the repository. Please try again later.'))

    ### Logging utilities
    # This log will be saved in a DepositRecord later on, so make sure
    # you use this logging so that you can inspect what went wrong
    # with a particular deposit later on.

    def log(self, line):
        """
        Logs a line in the protocol log.
        """
        self._logs += line+'\n'

    def log_request(self, r, expected_status_code, error_msg):
        """
        Logs an HTTP request and raises an error if the status code is unexpected.
        """
        self.log('--- Request to %s\n' % r.url)
        self.log('Status code: %d (expected %d)\n' %
                 (r.status_code, expected_status_code))
        if r.status_code != expected_status_code:
            self.log('Server response:')
            self.log(r.text)
            self.log('')
            raise DepositError(error_msg)

    ### Repository preferences
    # This enables you to let users define preferences about their
    # deposits.

    def get_preferences(self, user):
        """
        Returns an instance of the preferences for a user.
        If the preferences already exist, they will be returned
        as an existing model instance. Otherwise, they will
        be returned as a fresh (unsaved) instance of that model.
        """
        if self.preferences_model is None:
            return
        MyPreferences = self.preferences_model
        preferences, _ = MyPreferences.objects.get_or_create(
                            user=user,
                            repository=self.repository)
        return preferences

    def get_preferences_form(self, user, *args, **kwargs):
        """
        Returns the preference form for a user.
        All other arguments are passed to the form initialization.
        """
        if (
            self.preferences_form_class is None or not
            callable(self.preferences_form_class)
        ):
            return

        prefs = self.get_preferences(user)
        kwargs['instance'] = prefs
        return self.preferences_form_class(*args, **kwargs)
