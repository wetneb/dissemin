import os
import pytest

from lxml import etree

from deposit.models import DDC
from deposit.models import License
from deposit.models import LicenseChooser
from deposit.models import UserPreferences
from papers.models import OaiRecord
from papers.models import Paper
from papers.models import Researcher
from publishers.models import Journal
from publishers.models import Publisher


@pytest.fixture(params=[True, False])
def abstract_required(db, request):
    """
    Sets abstract as required or not and returns value.
    """
    request.cls.protocol.repository.abstract_required=request.param
    request.cls.protocol.repository.save()

    return request.param


@pytest.fixture(params=[None, '2543-2454-2345-234X'])
def depositing_user(db, request, user_leibniz):
    """
    Depositing user with Researcher profile with and without ORCID
    """
    Researcher.create_by_name(
        user=user_leibniz,
        first=user_leibniz.first_name,
        last=user_leibniz.last_name,
        orcid=request.param,
    )

    user_leibniz.orcid = request.param

    return user_leibniz


@pytest.fixture(params=[True, False])
def ddc(request, db):
    """
    Run tests for protocol with repository having a DDC and not having a DDC
    """
    if request.param:
        all_ddc = DDC.objects.all()
        request.cls.protocol.repository.ddc.add(*all_ddc)
        return all_ddc
    else:
        return None


@pytest.fixture
def dissemin_xml_1_0():
    '''
    Loads a dissemin xml document ready to be manipulated and be validated
    '''
    directory = os.path.dirname(os.path.abspath(__file__))
    parser = etree.XMLParser(remove_blank_text=True)
    return etree.parse(os.path.join(directory, 'schema', 'test_data', 'dissemin_v1.0.xml'), parser).getroot()


@pytest.fixture(scope="session")
def dissemin_xsd_1_0():
    '''
    Loads dissemin xsd and prepares it as schema ready for validation.
    '''

    testdir = os.path.dirname(os.path.abspath(__file__))
    dissemin_xsd = etree.parse(os.path.join(testdir, 'schema','dissemin_v1.0.xsd'))
    return etree.XMLSchema(dissemin_xsd)


@pytest.fixture(params=['none', 'optional', 'required'])
def embargo(request):
    """
    Embargo with three simple values
    """
    request.cls.protocol.repository.embargo=request.param
    request.cls.protocol.repository.save()

    return request.param


@pytest.fixture
def dummy_oairecord(dummy_paper, dummy_oaisource):
    """
    Empty OaiRecord with FK to empty_paper and empty OaiSource
    """
    o = OaiRecord.objects.create(
        source=dummy_oaisource,
        about=dummy_paper,
        identifier='dummy',
    )

    return o


@pytest.fixture
def dummy_paper():
    """
    Just an empty paper
    """
    p =  Paper.objects.create(
        pubdate='2019-10-08',
    )

    return p


@pytest.fixture
def dummy_publisher():
    """
    Empty Publisher
    """
    p = Publisher.objects.create()

    return p


@pytest.fixture
def dummy_journal(dummy_publisher):
    """
    Empty Journal with FK to Publisher
    """
    j = Journal.objects.create(
        publisher=dummy_publisher,
    )

    return j


@pytest.fixture
def empty_user_preferences(db, user_isaac_newton):
    """
    Returns an empty UserPreferences object
    """
    user_prefs, unused = UserPreferences.objects.get_or_create(user=user_isaac_newton)
    return user_prefs


@pytest.fixture()
def license_alternative(db):
    """
    Returns an alternative test license
    Use this license, if you need two of them
    """

    license = License.objects.get_or_create(
        name="Alternative License",
        uri="https://dissem.in/deposit/license/alternative"
    )

    return license


@pytest.fixture()
def license_standard(db):
    """
    Returns a standard test license
    """

    license = License.objects.create(
        name="Standard License",
        uri="https://dissem.in/deposit/license/standard"
    )

    return license


@pytest.fixture(params=[True, False])
def license_chooser(db, request):
    """
    Creates a LicenseChooser object connected to repository and CC 0 license that is available by migration
    """
    if request.param:
        l = License.objects.get(uri='https://creativecommons.org/publicdomain/zero/1.0/')
        lc = LicenseChooser.objects.create(
            license=l,
            repository=request.cls.protocol.repository,
            transmit_id='cc-zero-1.0'
        )
        return lc
    else:
        return False


@pytest.fixture(params=[True, False])
def monkeypatch_paper_is_owned(request, monkeypatch):
    """
    Mokeypatch this function to have simpler fixtures. Both function values are resembled.
    """
    monkeypatch.setattr(Paper, 'is_owned_by', lambda *args, **kwargs: request.param)


@pytest.fixture
def request_fake_response():
    class R:
        pass

    r = R()
    r.status_code = 200
    r.text = 'Spanish Inquisition'
    r.url = 'https://dissem.in'

    return r


# This is a list of oairecords to be tested
metadata_publications = [
    'book-chapter_acute_interstitial_nephritis',
    'book-chapter_adaptive_multiagent_system_for_multisensor_maritime_surveillance',
    'book_god_of_the_labyrinth',
    'dataset_sexuality_assessment_in_older_adults_unique_situations',
    'journal-article_a_female_signal_reflects_mhc_genotype_in_a_social_primate',
    'journal-article_altes_und_neues_zum_strafrechtlichen_vorsatzbegriff',
    'journal-article_confrontation_with_heidegger',
    'journal-article_constructing_matrix_geometric_means',
    'journal-article_lobjet_de_la_dpression',
    'journal-issue_mode_und_gender',
    'other_assisting_configuration_based_feature_model_composition',
    'poster_development_of_new_gpe_conjugates_with_application_in_neurodegenerative_diseases',
    'preprint_nikomachische_ethik',
    'proceedings_sein_und_nichtsein',
    'proceedings-article_activitycentric_support_for_weaklystructured_business_processes',
    'proceedings-article_an_efficient_vofbased_rans_method_to_capture_complex_sea_states',
    'proceedings-article_cursos_efa',
    'reference-entry_chromatin_interaction_analysis_using_pairedend_tag_sequencing',
    'report_execution_of_targeted_experiments_to_inform_bison',
    'thesis_blue_mining_planung_des_abbaus_von_manganknollen_in_der_tiefsee',
]


@pytest.fixture(params=metadata_publications)
def upload_data(request, load_json):
    """
    Loads the above list of publications and returns form data the user has to fill in.
    """
    return load_json.load_upload(request.param)
