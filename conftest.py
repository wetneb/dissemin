import json
import os
import pytest
import re
import requests
import sys


from datetime import date
from html5validator import Validator as HTML5Validator
from io import BytesIO
from tempfile import NamedTemporaryFile

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.management import call_command
from django.urls import reverse

from deposit.models import Repository
from dissemin.settings import BASE_DIR
from dissemin.settings import POSSIBLE_LANGUAGE_CODES
from papers.baremodels import PAPER_TYPE_CHOICES
from papers.models import Department
from papers.models import Institution
from papers.models import Name
from papers.models import Paper
from papers.models import OaiRecord
from papers.models import OaiSource
from papers.models import Researcher
from publishers.models import Journal
from publishers.models import Publisher
from upload.models import UploadedPDF


@pytest.fixture
def load_json(db, oaisource):
    """
    This fixture returns an object with which you can load various JSON fixtures. It deletes the created objects after test has finished.
    """

    l = LoadJSON()
    yield l
    for obj in l.objects:
        if obj.id is not None:
            obj.delete()


@pytest.fixture
def simple_logo():
    """
    Fixture for a simple png image for repositories
    """
    # 1x1 px image
    simple_png_image = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x07tIME\x07\xdf\n\x12\x0c+\x19\x84\x1d/"\x00\x00\x00\x19tEXtComment\x00Created with GIMPW\x81\x0e\x17\x00\x00\x00\x0cIDAT\x08\xd7c\xa8\xa9\xa9\x01\x00\x02\xec\x01u\x90\x90\x1eL\x00\x00\x00\x00IEND\xaeB`\x82'
    logo = InMemoryUploadedFile(
        BytesIO(simple_png_image),
        None,
        'logo.png',
        'image/png', 
        len(simple_png_image),
        None,
        None
    )
    return logo


@pytest.fixture
def oaisource(db):
    """
    Returns a class from which you can create several oaisources. It deletes the created objects after test has finished.
    """

    los = LoadOaiSource()
    yield los
    for obj in los.objects:
        if obj.id is not None:
            obj.delete()


@pytest.fixture
def dummy_oaisource(oaisource):
    """
    Provides a dummy OaiSource if you just need a OaiSource, but do not do anything with it. Use this, if you need just a single OaiSource.
    """
    return oaisource.dummy_oaisource()


@pytest.fixture
def repository(db, simple_logo, oaisource):
    """
    Returns a class from which you can create several repositories. Use if you need more than one repository.
    """
    class Dummy():
        """
        Dummy class to gather the different functions.
        """
        def __init__(self):
            self.objects = []

        def dummy_repository(self):
            """
            Returns a dummy_repository with a faked dummy-protocol where you need only the repository, but do not anything with it.
            """
            repo = Repository.objects.create(
                name='Dummy Test Repository',
                description='Test repository',
                logo=simple_logo,
                protocol='No-Protocol',
                oaisource=oaisource.dummy_oaisource(),
            )
            self.objects.append(repo)
            return repo

        def sword_mets_repository(self):
            """
            Returns a new SWORD METS repository using SWORDMETSProtocol. SWORDMETSProtocol is an abstract class, so you can't really do anything with it and this repository.
            """
            repo = Repository.objects.create(
                name='Repository SWORD METS',
                description='SOWRD METS Test repository',
                logo=simple_logo,
                username='dissemin',
                password='dissemin',
                protocol='SWORDMETSProtocol',
                endpoint='https://deposit.dissem.in/sword_mets/',
                oaisource=oaisource.dummy_oaisource(),
            )
            self.objects.append(repo)
            return repo

        def sword_mods_repository(self):
            """
            Returns a new SWORD METS MODS repository using SWORDMETSMODSProtocol.
            """
            repo = Repository.objects.create(
                name='Repository SWORD MODS',
                description='SWORD MODS Test Repository',
                logo=simple_logo,
                username='dissemin',
                password='dissemin',
                protocol='SWORDMETSMODSProtocol',
                endpoint='https://deposit.dissem.in/sword_mods/',
                oaisource=oaisource.base_oaisource(),
                abstract_required=False,
            )
            self.objects.append(repo)
            return repo


    dummy = Dummy()
    yield dummy
    for obj in dummy.objects:
        obj.delete()


@pytest.fixture
def dummy_repository(repository):
    """
    Returns a dummy_repository with a faked dummy-protocol where you need only the repository, but do not anything with it. Use this if you need a single dummy repository.
    """
    return repository.dummy_repository()


@pytest.fixture
def book_god_of_the_labyrinth(load_json):
    """
    Returns a paper, type book
    """
    p = load_json.load_paper('book_god_of_the_labyrinth')
    return p


@pytest.fixture
def user_leibniz(django_user_model):
    """
    Returns user Gottfried Wilhelm Leibniz
    """
    leibnizg = django_user_model.objects.create(
        username='leibnizg',
        first_name='Gottfried',
        last_name='Leibniz',
        email='gottfried.leibniz@tib.eu'
    )

    return leibnizg


@pytest.fixture
def user_isaac_newton(db):
    """
    Returns the user Isaac Newton
    """
    user = User.objects.create_user(
        username='newton',
        first_name='Isaac',
        last_name='Newton',
        email='isaac.newton@scientists.free',
    )
    yield user
    user.delete()


@pytest.fixture(scope="class")
def blank_pdf_path():
    testdir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(testdir, 'upload', 'tests', 'data', 'blank.pdf')
    return path


@pytest.fixture(scope="class")
def blank_pdf(blank_pdf_path):
    with open(blank_pdf_path, 'rb') as f:
            pdf = f.read()
    return pdf

@pytest.fixture
def uploaded_pdf(user_leibniz, blank_pdf):
    """
    A simple uploaded pdf of user leibniz.
    """
    pdf = UploadedPDF.objects.create(
        user=user_leibniz,
    )
    pdf.file.save('blank.pdf', ContentFile(blank_pdf))
    return pdf

"""
Depending on the environment variable DISSEMIN_TEST_ALL_LANGAUAGES sets the languages to be tested. If not set, use english, otherwise all languages from settings.POSSIBLE_LANGUAGE_CODES
"""
if 'DISSEMIN_TEST_ALL_LANGUAGES' in os.environ:
    TEST_LANGUAGES = POSSIBLE_LANGUAGE_CODES
else:
    TEST_LANGUAGES = ['en-us']


@pytest.fixture(params=TEST_LANGUAGES)
def check_page(request, dissemin_base_client, validator_tools):
    """
    Checks status of page and checks html. 
    """
    def checker(status, *args, **kwargs):
        vt = validator_tools
        vt.client = kwargs.pop('client', dissemin_base_client)
        vt.client.cookies.load({settings.LANGUAGE_COOKIE_NAME : request.param})
        vt.check_page(status, *args, **kwargs)

    return checker


@pytest.fixture(params=TEST_LANGUAGES)
def check_html(request, validator_tools):
    """
    Checks html
    """
    def checker(response):
        vt = validator_tools
        vt.check_html(response)

    return checker



@pytest.fixture(params=TEST_LANGUAGES)
def check_url(request, validator_tools):
    """
    Checks status and html of a URL
    """

    def checker(status, url):
        vt = validator_tools
        vt.client.cookies.load({settings.LANGUAGE_COOKIE_NAME : request.param})
        vt.check_url(status, url)

    return checker

@pytest.fixture
def check_status(dissemin_base_client, validator_tools):
    """
    Checks the status of a page
    """
    def checker(status=None, *args, **kwargs):
        vt = validator_tools
        vt.client = kwargs.pop('client', dissemin_base_client)
        vt.check_status(status, *args, **kwargs)

    return checker


@pytest.fixture
def check_permanent_redirect(validator_tools):
    """
    Checks for 301 and if 'url' given if redirect url is correct
    """
    def checker(*args, **kwargs):
        vt = validator_tools
        vt.check_permanent_redirect(*args, **kwargs)

    return checker


@pytest.fixture
def dissemin_base_client(client):
    """
    Returns a client which sends HTTP_HOST in headers.
    This is needed because some pages unfortunately produce internal links with domain
    """
    client.defaults = { 'HTTP_HOST' : 'localhost'}

    return client


@pytest.fixture
def authenticated_client(dissemin_base_client, django_user_model):
    """
    Returns a logged in client
    """
    username = "authenticated_user"
    password = "secret"
    u = django_user_model.objects.create_user(username=username, password=password)
    dissemin_base_client.login(username=username, password=password)
    dissemin_base_client.user = u
    return dissemin_base_client


@pytest.fixture
def authenticated_client_su(dissemin_base_client, db, django_user_model):
    """
    Returns a logged in client
    """
    username = "authenticated_user"
    password = "secret"
    u = django_user_model.objects.create_user(username=username, password=password)
    u.is_superuser = True
    u.save()
    dissemin_base_client.login(username=username, password=password)
    return dissemin_base_client


@pytest.fixture
def validator_tools(dissemin_base_client, settings):
    class ValidatorTools():
        """
        Class that collect tools for validating pages
        """

        ignore_re = [
            'Attribute "dp_config" not allowed on element', # Django Bootstrap DatetimePicker uses this extra attribute which is considered invalid by W3C validator. We filter that out.
        ]

        def __init__(self, client, settings):
            self.client = client
            # Deactivate Django tool bar, so that it does not interfere with tests
            settings.DEBUG_TOOLBAR_CONFIG = {'SHOW_TOOLBAR_CALLBACK': lambda r: False}

        def check_html(self, response, status=None):
            """
            Checks if a page returns valid html
            """
            if status is not None:
                assert response.status_code == status
            # If USE_VNU_SERVER is in os.environ, we use the VNU server for validation, otherwise we use html5validator / subprocess
            # html5validator is very slow due to invoked subprocess
            if 'USE_VNU_SERVER' in os.environ:
                validation_result = self.validation_vnu_server(response.content)
            else:
                validation_result = self.validation_subprocess(response.content)

            # We fetch the AssertionError and raise it, to print the file with line numbers to stderr, because the written file will be removed
            try:
                assert validation_result == 0
            except AssertionError:
                print("THIS IST WHAT THE HTML LOOKS LIKE")
                for index, item in enumerate(response.content.decode('utf-8').split("\n")[:-1]):
                    print("{:3d} {}".format(index + 1, item))
                raise

        def check_page(self, status, *args, **kwargs):
            """
            Fetches and checks page
            """
            return self.check_html(self.get_page(*args, **kwargs), status)

        def check_status(self, status, *args, **kwargs):
            """
            Checks status
            """
            assert self.get_page(*args, **kwargs).status_code == status

        def check_url(self, status, url):
            """
            Fetches and checks url
            """
            self.check_html(self.client.get(url))

        def check_permanent_redirect(self, *args, **kwargs):
            """
            Checks permanent redirect, 301 as status and new url
            """
            target_url = kwargs.pop('url', None)
            response = self.get_page(*args, **kwargs)
            assert response.status_code == 301
            if target_url is not None:
                assert response.url == target_url

        def get_page(self, *args, **kwargs):
            """
            Gets a page with reverse
            """
            urlargs = kwargs.copy()
            if 'getargs' in kwargs:
                del urlargs['getargs']
                return self.client.get(reverse(*args, **urlargs), kwargs['getargs'])
            return self.client.get(reverse(*args, **kwargs))


        def validation_vnu_server(self, html):
            """
            Does html validation via vnu server. The postprocessing is taken from html5validator to have same output
            :param html: html
            :returns: string of errors
            """
            # Getting the errors
            headers = {
                'Content-Type' : 'text/html; charset=utf-8'
            }
            r = requests.post('http://localhost:8888/?out=gnu&level=error', data=html, headers=headers).text
            # Convert fancy quotes into normal quotes
            r = r.replace('“', '"')
            r = r.replace('”', '"')
            r = r.splitlines()
            # Filter results by regexp
            for i in self.ignore_re:
                regex = re.compile(i)
                r = [l for l in r if not regex.search(l)]
            # Send errors to stderr
            if r:
                print("\n".join(r), file=sys.stderr)

            return len(r)

        def validation_subprocess(self, html):
            """
            Does html validation via subprocess and returns a string of errors
            :param html: html
            :returns: string of errors
            """
            # We need a temporary file
            with NamedTemporaryFile(delete=False) as fh:
                fh.write(html)
            validator = HTML5Validator(
                errors_only=True,
                ignore_re=self.ignore_re,
            )
            result = validator.validate([fh.name])
            # tidy up the temporary file (mainly for local usage, not Travis)
            try:
                os.remove(fh.name)
            except:
                pass
            return result

    vt = ValidatorTools(dissemin_base_client, settings)
    return vt


@pytest.fixture(scope="session")
def css_validator():
    """
    Returns a function that takes a directory and validates all of its css files
    """
    def checker(directory):
        validator = HTML5Validator(errors_only=True)
        assert validator.validate([f for f in os.listdir(directory) if f.endswith('.css')]) == 0

    return checker


@pytest.fixture
def rendering_get_page():
    """
    Returns a function that gets a page. Call this function with a client that may or may not be logged in.
    """
    def f(client, *args, **kwargs):
        """
        Gets a page.
        """
        urlargs = kwargs.copy()
        if 'getargs' in kwargs:
            del urlargs['getargs']
            return client.get(reverse(*args, **urlargs), kwargs['getargs'])
        return client.get(reverse(*args, **kwargs))

    return f


# Helper classes. Do not use them directly in your tests.

class LoadJSON():
    """
    Class that carries the various functions. Use the corresponding fixture instead of this class directly.
    """
    objects = []

    def load_upload(self, f):
        """
        Loads oairecord, corresponding paper and form data that the user has to fill in
        """
        f_name = os.path.join(BASE_DIR, 'test_data', 'form', 'upload',  f + '.json')
        with open(f_name, 'r') as json_file:
            data = json.load(json_file)
        data['load_name'] = f
        p, o = self.load_oairecord(f)
        data['paper'] = p
        data['oairecord'] = o
        return data

    def load_paper(self, f):
        """
        Loads the given Paper
        """
        f_name = os.path.join(BASE_DIR, 'test_data', 'paper', f + '.json')
        with open(f_name, 'r') as json_file:
            data = json.load(json_file)
        p = Paper.objects.get_or_create(**data)[0]
        self.objects.append(p)
        return p

    def load_oairecord(self, f):
        """
        Loads the given OaiRecord and the related paper and returns both
        If a publisher or journal is given, both are loaded, but not returned
        """
        f_name = os.path.join(BASE_DIR, 'test_data', 'oairecord', f + '.json')
        with open(f_name, 'r') as json_file:
            data = json.load(json_file)
        p = self.load_paper(data['about'])
        data['about'] = p
        if 'source' not in data:
            data['source'] = LoadOaiSource.base_oaisource()
        if 'journal' in data:
            journal = self.load_journal(data['journal'])[0]
            data['journal'] = journal
        if 'publisher' in data:
            publisher = self.load_publisher(data['publisher'])
            data['publisher'] = publisher
        o = OaiRecord.objects.get_or_create(**data)[0]
        self.objects.append(o)
        return p, o

    def load_publisher(self, f):
        """
        Loads the given publisher
        """
        f_name = os.path.join(BASE_DIR, 'test_data', 'publisher', f + '.json')
        with open(f_name, 'r') as json_file:
            data = json.load(json_file)
        p = Publisher.objects.get_or_create(**data)[0]
        self.objects.append(p)
        return p

    def load_journal(self, f):
        """
        Loads the given journal and its publisher and returns both
        """
        f_name = os.path.join(BASE_DIR, 'test_data', 'journal', f + '.json')
        with open(f_name, 'r') as json_file:
            data = json.load(json_file)
        p = self.load_publisher(data['publisher'])
        data['publisher'] = p
        j = Journal.objects.get_or_create(**data)[0]
        self.objects.append(j)
        return j, p


class LoadOaiSource():
    """
    Class that has several functions for creation of OaiSources. Use the corresponding fixture instead of this class directly.
    """
    objects = []

    def dummy_oaisource(self):
        """
        Provides a dummy OaiSource if you just need a OaiSource, but do not do anything with it
        """
        oaisource, unused = OaiSource.objects.get_or_create(
            identifier='dummy-test',
            name='Dummy OaiSource',
            default_pubtype=PAPER_TYPE_CHOICES[0][0],
        )
        self.objects.append(oaisource)
        return oaisource

    @staticmethod
    def base_oaisource():
        """
        Provides BASE OaiSource. It is in the database from a migration. We do not add it to the list of to be deleted OaiSources
        """
        return OaiSource.objects.get(identifier='base')


# Fixtures and Functions for load_test_data, which should prefereably not be used as it loads a lot of things
def get_researcher_by_name(first, last):
    n = Name.lookup_name((first, last))
    return Researcher.objects.get(name=n)


@pytest.fixture
def load_test_data(request, db, django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command('loaddata', 'test_dump.json')
        self = request.cls
        self.i = Institution.objects.get(name='ENS')
        self.d = Department.objects.get(name='Chemistry dept')
        self.di = Department.objects.get(name='Comp sci dept')

        self.r1 = get_researcher_by_name('Isabelle', 'Aujard')
        self.r2 = get_researcher_by_name('Ludovic', 'Jullien')
        self.r3 = get_researcher_by_name('Antoine', 'Amarilli')
        self.r4 = get_researcher_by_name('Antonin', 'Delpeuch')
        self.r5 = get_researcher_by_name('Terence', 'Tao')
        self.hal = OaiSource.objects.get(identifier='hal')
        self.arxiv = OaiSource.objects.get(identifier='arxiv')
        self.lncs = Journal.objects.get(issn='0302-9743')
        self.acm = Journal.objects.get(issn='1529-3785').publisher


@pytest.fixture
def rebuild_index(request):
    rebuild_index = (
        lambda: call_command('rebuild_index', interactive=False)
    )
    rebuild_index()
    request.addfinalizer(rebuild_index)
