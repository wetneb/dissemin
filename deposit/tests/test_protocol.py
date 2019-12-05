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

from datetime import date
from io import BytesIO
import unittest
import django.test
import copy
import pytest
import os

from deposit.models import DDC
from deposit.models import License
from deposit.models import LicenseChooser
from deposit.protocol import DepositError
from deposit.protocol import DepositResult
from deposit.protocol import RepositoryProtocol
from deposit.registry import protocol_registry
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.base import ContentFile
from django.forms import Form
from django.urls import reverse
from papers.models import OaiSource
from papers.models import OaiRecord
from papers.models import Paper
from deposit.tasks import refresh_deposit_statuses
from upload.models import UploadedPDF


class MetaTestProtocol():
    """
    This class contains some tests that every implemented protocol shall pass. The tests are not executed as members of this class, but of any subclass.
    If you change one of the tested functions in your subclassed protocol, please override the test in the corresponding test class.
    """

    @pytest.mark.parametrize('embargo', [None, date.today()])
    def test_add_embargo_date_to_deposit_result(self, embargo):
        """
        If an embargo is set, add to deposit record, otherwise not
        """
        # We just set cleaned data directly
        f = Form()
        f.cleaned_data = dict()
        if embargo is not None:
            f.cleaned_data['embargo'] = embargo
        dr = DepositResult(status='pending')
        dr = self.protocol._add_embargo_date_to_deposit_result(dr, f)
        assert dr.embargo_date == embargo


    def test_add_license_to_deposit_result(self, license_chooser):
        """
        If a license is selected, add to deposit record, otherwise not
        """
        # We just set the cleaned data directly
        f = Form()
        f.cleaned_data = dict()
        if license_chooser:
            f.cleaned_data['license'] = license_chooser
        dr = DepositResult(status='pending')
        dr = self.protocol._add_license_to_deposit_result(dr, f)
        if license_chooser:
            assert dr.license == license_chooser.license
        else:
            assert dr.license == None


    def test_deposit_page_status(self, authenticated_client, rendering_get_page, book_god_of_the_labyrinth):
        """
        Test the deposit page for HTTP Response 200
        """
        r = rendering_get_page(authenticated_client, 'upload_paper', kwargs={'pk': book_god_of_the_labyrinth.pk})
        assert r.status_code == 200


    def test_get_depositor_orcid(self, depositing_user):
        """
        Tested function returns the ORCID of the depositing user if available
        """
        self.protocol.user = depositing_user

        assert self.protocol._get_depositor_orcid() == depositing_user.orcid


    def test_get_form(self, book_god_of_the_labyrinth, abstract_required, ddc, embargo, license_chooser):
        self.protocol.paper = book_god_of_the_labyrinth
        form = self.protocol.get_form()
        assert form.fields['abstract'].required == abstract_required
        if ddc:
            assert 'ddc' in form.fields
        else:
            assert 'ddc' not in form.fields
        if embargo == 'required':
            assert form.fields['embargo'].required == True
        elif embargo == 'optional':
            assert form.fields['embargo'].required == False
        else:
            assert 'embargo' not in form.fields
        if license_chooser:
            assert 'license' in form.fields
        else:
            assert 'license' not in form.fields
        assert 'paper_id' in form.fields


    def test_get_bound_form(self, book_god_of_the_labyrinth, abstract_required, ddc, embargo, license_chooser):
        self.protocol.paper = book_god_of_the_labyrinth
        data = {
            'paper_pk' : book_god_of_the_labyrinth.pk
        }
        if abstract_required:
            data['abstract'] = 'Simple abstract'
        if ddc:
            data['ddc'] = ddc
        if license_chooser:
            data['license'] = license_chooser.pk
        if embargo == 'required':
            data['embargo'] = '2019-10-10'

        form = self.protocol.get_bound_form(data=data)
        if not form.is_valid():
            print(form.errors)
            raise AssertionError("Form not valid")


    def test_get_form_return_type(self, book_god_of_the_labyrinth, user_isaac_newton):
        """
        Return type of get_form shall by a form
        """
        self.protocol.init_deposit(book_god_of_the_labyrinth ,user_isaac_newton)
        form = self.protocol.get_form()
        assert isinstance(form, Form)


    @pytest.mark.parametrize('pub_name', [None, 'BMC'])
    def test_get_publisher_name_from_oairecord(self, dummy_oairecord, pub_name):
        """
        Tests if the publisher name is returned or if not available: None
        """
        dummy_oairecord.publisher_name = pub_name
        self.protocol.publication = dummy_oairecord

        assert self.protocol._get_publisher_name() == pub_name


    def test_get_publisher_name_from_publisher(self, dummy_oairecord, dummy_publisher):
        """
        Tests if the publisher name is returned from the publisher object
        """
        dummy_publisher.name = 'BMC'
        dummy_publisher.save()
        dummy_oairecord.publisher = dummy_publisher
        dummy_oairecord.save()
        self.protocol.publication = dummy_oairecord

        assert self.protocol._get_publisher_name() == dummy_publisher.name


    def test_get_sherpa_romeo_id(self, dummy_oairecord, dummy_publisher):
        """
        Tests if the SHERPA/RoMEO id is returned from the publisher object
        """
        romeo_id = 1
        dummy_publisher.romeo_id = romeo_id
        dummy_publisher.save()
        dummy_oairecord.publisher = dummy_publisher
        dummy_oairecord.save()
        self.protocol.publication = dummy_oairecord

        assert self.protocol._get_sherpa_romeo_id() == romeo_id


    def test_get_sherpa_romeo_id_no_publisher(self, dummy_oairecord):
        """
        If no publisher for OaiRecord if found, expect ``None``.
        """
        self.protocol.publication = dummy_oairecord

        assert self.protocol._get_sherpa_romeo_id() == None


    def test_init_deposit(self, user_isaac_newton, book_god_of_the_labyrinth):
        """
        init_deposit shall return a bool
        """
        result = self.protocol.init_deposit(book_god_of_the_labyrinth, user_isaac_newton)
        assert self.protocol.paper == book_god_of_the_labyrinth
        assert self.protocol.user == user_isaac_newton
        assert self.protocol._logs == ''
        assert result == True


    def test_get_ddcs(self, db):
        """
        Function should return a queryset of length > 1 of DDCs if DDCs are choosen
        """
        for ddc in DDC.objects.all():
            self.protocol.repository.ddc.add(ddc)

        assert len(self.protocol._get_ddcs()) == DDC.objects.all().count()


    def test_get_ddcs_none(self):
        """
        Function should return ``None`` if noe DDS selected for repository
        """
        assert self.protocol._get_ddcs() == None


    def test_get_licenses(self, db):
        """
        Function should return a queryset of of length > 1 of  LicenseChoosers if LicenseChoosers are choosen
        """
        for uri in ['https://creativecommons.org/publicdomain/zero/1.0/', 'https://creativecommons.org/licenses/by/4.0/', 'http://creativecommons.org/licenses/by-nd/4.0/']:
            license = License.objects.get(uri=uri)
            LicenseChooser.objects.create(
                license=license,
                repository=self.protocol.repository,
            )

        assert len(self.protocol._get_licenses()) == 3


    def test_get_licenses_none(self):
        """
        Function should return none if no LicenseChooser selected for repository
        """
        assert self.protocol._get_licenses() == None


    def test_get_preferences(self, user_isaac_newton):
        """
        If a protocol has preferences, return object, else ``None``
        """
        if self.protocol.preferences_model is None:
            assert self.protocol.get_preferences(user_isaac_newton) == None
        else:
            assert isinstance(self.protocol.get_preferences(user_isaac_newton), self.protocol.preferences_model)


    def test_log(self):
        """
        Simply append a line to self._logs
        """
        msg = 'Spanish Inquisition'
        self.protocol.log(msg)
        assert self.protocol._logs == msg + "\n"


    def test_log_request(self, request_fake_response):
        """
        Tests the log request.
        """
        assert self.protocol.log_request(request_fake_response, 200, 'Does not serve') == None


    def test_log_request_error(self, request_fake_response):
        """
        Tests the log request
        """
        with pytest.raises(DepositError):
            self.protocol.log_request(request_fake_response, 201, 'Does not serve')


    def test_protocol_identifier(self):
        """
        Identifier should exist
        """
        assert len(self.protocol.protocol_identifier()) > 1


    def test_publication_with_fk(self, db, dummy_oairecord, dummy_journal, dummy_publisher):
        """
        If journal and publisher are linked, this OaiRecord should be first. We add necessary data and then add another OaiRecord that should not be fetched.
        """
        self.protocol.paper = dummy_oairecord.about

        dummy_oairecord.journal = dummy_journal
        dummy_oairecord.publisher = dummy_publisher
        dummy_oairecord.priority = 10
        dummy_oairecord.save()

        second_oairecord = copy.copy(dummy_oairecord)
        second_oairecord.pk = None
        second_oairecord.priority = 9
        second_oairecord.identifier += '_2'
        second_oairecord.save()

        third_oairecord = copy.copy(dummy_oairecord)
        third_oairecord.pk = None
        third_oairecord.identifier += '_3'
        third_oairecord.journal = None
        third_oairecord.save()

        assert self.protocol.publication.pk == dummy_oairecord.pk


    def test_publication_with_names(self, db, dummy_oairecord):
        """
        If no journal or publisher are linked, the OaiRecord with journal_title and publisher_name should be first. We add necessary data and then add a second OaiRecord that should not be fetched.
        """
        self.protocol.paper = dummy_oairecord.about

        dummy_oairecord.journal_title = 'Journal Title'
        dummy_oairecord.publisher_name = 'Publisher Name'
        dummy_oairecord.priority = 10
        dummy_oairecord.save()

        second_oairecord = copy.copy(dummy_oairecord)
        second_oairecord.pk = None
        second_oairecord.priority = 9
        second_oairecord.identifier += '_2'
        second_oairecord.save()

        third_oairecord = copy.copy(dummy_oairecord)
        third_oairecord.pk = None
        third_oairecord.identifier += '_3'
        third_oairecord.journal_title = ''
        third_oairecord.save()

        assert self.protocol.publication.pk == dummy_oairecord.pk


    def test_publication_only_priority(self, db, dummy_oairecord):
        """
        If no OaiRecord has any information about journal or publisher, just give first
        """
        self.protocol.paper = dummy_oairecord.about

        dummy_oairecord.priority = 10
        dummy_oairecord.save()

        second_oairecord = copy.copy(dummy_oairecord)
        second_oairecord.pk = None
        second_oairecord.priority = 9
        second_oairecord.identifier += '_2'
        second_oairecord.save()

        assert self.protocol.publication.pk == dummy_oairecord.pk


    def test_publication_no_result(self, dummy_paper):
        """
        If no OaiRecord can be found, we expect ``None``. Should in practice not happen.
        """
        self.protocol.paper = dummy_paper

        assert self.protocol.publication == None







    @pytest.mark.parametrize('on_todolist', [True, False])
    @pytest.mark.parametrize('splash_url, expected_splash_url', [(None, type(None)), ('https://repository.dissem.in/1/spam.pdf', OaiRecord)])
    def test_submit_deposit_wrapper(self, splash_url, expected_splash_url, on_todolist, book_god_of_the_labyrinth, depositing_user, monkeypatch):
        """
        We monkeypatch the submit_deposit to return a DepositResult.
        """
        self.protocol.paper = book_god_of_the_labyrinth
        self.protocol.user = depositing_user

        if on_todolist:
            book_god_of_the_labyrinth.todolist.add(self.protocol.user)

        dr = DepositResult(splash_url=splash_url)
        monkeypatch.setattr(self.protocol, 'submit_deposit', lambda *args, **kwargs: dr)

        deposit_result = self.protocol.submit_deposit_wrapper()

        assert isinstance(deposit_result, DepositResult)
        assert isinstance(deposit_result.oairecord, expected_splash_url)
        assert book_god_of_the_labyrinth.todolist.filter(pk=self.protocol.user.pk).exists() == False


    @pytest.mark.parametrize('on_todolist', [True, False])
    @pytest.mark.parametrize('exc', [DepositError, Exception])
    def test_submit_deposit_wrapper_exception(self, book_god_of_the_labyrinth, depositing_user, on_todolist, exc, monkeypatch):
        """
        Something went wrong when depositing. Exceptions must be fetched and Deposit status status must be "failed". To do that we simply monkeypatch submit_deposit
        """
        self.protocol.paper = book_god_of_the_labyrinth
        self.protocol.user = depositing_user

        if on_todolist:
            book_god_of_the_labyrinth.todolist.add(self.protocol.user)

        def submit_deposit(self, *args, **kwargs):
            raise exc

        monkeypatch.setattr(self.protocol, 'submit_deposit', submit_deposit)

        deposit_result = self.protocol.submit_deposit_wrapper()

        assert deposit_result.status == 'failed'
        assert book_god_of_the_labyrinth.todolist.filter(pk=self.protocol.user.pk).exists() == on_todolist


    def test_protocol_registered(self):
        """
        This test makes sure that each tested protocol is registered. You can temporarly override this function in your corresponding protocol test as long as you do not have it registered.
        """
        p = protocol_registry.get(self.protocol.__class__.__name__)
        assert issubclass(p, RepositoryProtocol) == True


# 1x1 px image used as default logo for the repository
simple_png_image = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x07tIME\x07\xdf\n\x12\x0c+\x19\x84\x1d/"\x00\x00\x00\x19tEXtComment\x00Created with GIMPW\x81\x0e\x17\x00\x00\x00\x0cIDAT\x08\xd7c\xa8\xa9\xa9\x01\x00\x02\xec\x01u\x90\x90\x1eL\x00\x00\x00\x00IEND\xaeB`\x82'

class DepositTest(django.test.TestCase):
    def test_refresh_deposit_statuses(self):
        # TODO: set up some DepositRecords + repository and protocol, to
        # so that this task actually does something
        refresh_deposit_statuses()

@pytest.mark.usefixtures("load_test_data", "rebuild_index")
class ProtocolTest(django.test.TestCase):
    """
    Set of generic tests that any protocol should pass.
    Note: This class is going to deprecated and is no longer maintained.
    """

    def __init__(self, *args, **kwargs):
        super(ProtocolTest, self).__init__(*args, **kwargs)

    def setUp(self):
        if type(self) is ProtocolTest:
            raise unittest.SkipTest("Base test")
        self.p1 = Paper.get_or_create(
                "This is a test paper",
                [self.r1.name, self.r2.name, self.r4.name],
                date(year=2014, month=2, day=15))

        self.username = 'mydepositinguser'
        self.password = 'supersecret'
        self.user = User.objects.create_user(username=self.username, email="my@email.com", password=self.password)
        path = os.path.join(settings.BASE_DIR, 'upload', 'tests', 'data', 'blank.pdf')
        with open(path, 'rb') as f:
            blank_pdf = f.read()

        self.pdf = UploadedPDF.objects.create(
            user=self.user,
        )
        self.pdf.file.save('blank.pdf', ContentFile(blank_pdf))


    def setUpForProtocol(self, protocol_class, repository):

        self.oaisource, _ = OaiSource.objects.get_or_create(
            identifier='deposit_oaisource',
            name='Repository OAI source',
            default_pubtype='preprint')
        logo = InMemoryUploadedFile(
                BytesIO(simple_png_image),
                None, 'logo.png',
                'image/png', len(simple_png_image), None, None)
        self.repo = repository
        self.repo.oaisource = self.oaisource
        self.repo.logo = logo
        if not self.repo.description:
            self.repo.description = 'brsuatiercs'
        if not self.repo.name:
            self.repo.name = 'Test Repository'
        self.repo.protocol = protocol_class.__name__
        self.repo.save()
        protocol_registry.register(protocol_class)
        self.proto = protocol_class(self.repo)
        self.form = None


    def test_protocol_identifier(self):
        self.assertTrue(len(self.proto.protocol_identifier()) > 1)

    def test_init_deposit(self):
        retval = self.proto.init_deposit(self.p1, self.user)
        self.assertIs(type(retval), bool)

    def test_get_form_return_type(self):
        self.proto.init_deposit(self.p1, self.user)
        retval = self.proto.get_form()
        self.assertIsInstance(retval, Form)

    def test_deposit_page(self):
        self.assertEqual(self.user.username, self.username)
        client = django.test.Client(HTTP_HOST='localhost')
        self.assertTrue(client.login(username=self.username, password=self.password))
        r = client.get(reverse('upload_paper', kwargs={'pk': self.p1.pk}))
        self.assertEqual(r.status_code, 200)

    def dry_deposit(self, paper, **form_fields):
        """
        This is not a test by itself - it's a method
        subclasses can call to create a fake deposit
        (if the protocol supports it!)
        """
        return self.deposit(paper, dry_run=True, **form_fields)

    def deposit(self, paper, dry_run=False, **form_fields):
        enabled = self.proto.init_deposit(paper, self.user)
        self.assertTrue(enabled)

        licenses = LicenseChooser.objects.by_repository(repository=self.repo)
        args = self.proto.get_form_initial_data(licenses=licenses)
        args.update(form_fields)
        # The forms needs the pk of LicenceChooser object
        args['license'] = self.lc.pk

        form = self.proto.get_bound_form(args)
        if not form.is_valid():
            print(form.errors)
        self.assertTrue(form.is_valid())
        pdf = self.pdf
        deposit_result = self.proto.submit_deposit_wrapper(pdf,
                                                           form, dry_run=dry_run)
        self.assertIsInstance(deposit_result, DepositResult)
        self.assertIsInstance(deposit_result.additional_info, list)
        for i in deposit_result.additional_info:
            self.assertNotEqual(i.get('label'), None)
            self.assertNotEqual(i.get('value'), None)
        return deposit_result

    def assertEqualOrLog(self, a, b):
        """
        Same as assertEqual but prints logs before failing
        if the two quantities are not equal.
        """
        if a != b:
            print(self.proto._logs)
        self.assertEqual(a, b)

class ProtocolRegistryTest(django.test.TestCase):
    def test_get(self):
        c = protocol_registry.get('ZenodoProtocol')
        self.assertTrue(issubclass(c, RepositoryProtocol))

