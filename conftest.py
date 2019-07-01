import json
import os
import pytest

from datetime import date
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.urls import reverse

from deposit.models import ClassificationSubject
from deposit.models import ClassificationSystem
from deposit.models import Repository
from dissemin.settings import BASE_DIR
from papers.baremodels import PAPER_TYPE_CHOICES
from papers.models import Paper
from papers.models import OaiSource
from papers.models import OaiRecord
from papers.models import OaiSource
from publishers.models import Journal
from publishers.models import Publisher


@pytest.fixture
def load_json(db):
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
def rendering_authenticated_client(client, django_user_model):
    """
    Returns a logged in client
    """
    username = "rendering_authenticated_user"
    password = "secret"
    u = django_user_model.objects.create_user(username=username, password=password)
    client.login(username=username, password=password)
    yield client
    u.delete()


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

    def load_classification_system(self, f, repository):
        """
        Loads an emtpy classification system. Requires an repository object to work
        """
        f_name = os.path.join(BASE_DIR, 'test_data', 'classification', 'system', f + '.json')
        with open(f_name, 'r') as json_file:
            data = json.load(json_file)
        data['repository'] = repository
        cs = ClassificationSystem.objects.get_or_create(data)[0]
        self.objects.append(cs)
        return cs

    def load_classification_subject(self, f, repository):
        """
        Loads a classification subject. Requires an repository object to work
        """
        f_name = os.path.join(BASE_DIR, 'test_data', 'classification', 'subject', f + '.json')
        with open(f_name, 'r') as json_file:
            data = json.load(json_file)
        csy = self.load_classification_system(data['classification_system'], repository)
        data['classification_system'] = csy
        cs = ClassificationSubject.objects.get_or_create(data)[0]
        self.objects.append(cs)
        return cs



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
