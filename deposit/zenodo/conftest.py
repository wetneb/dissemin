import pytest

from papers.models import OaiSource
from deposit.models import License
from deposit.models import LicenseChooser
from deposit.models import Repository
from deposit.zenodo.protocol import ZenodoProtocol


@pytest.fixture
def license_chooser(db, request):
    """
    Creates a LicenseChooser object connected to repository and CC 0 license that is available by migration
    """
    l = License.objects.get(uri='https://creativecommons.org/publicdomain/zero/1.0/')
    lc = LicenseChooser.objects.create(
        license=l,
        repository=request.cls.protocol.repository,
        transmit_id='cc-zero-1.0'
    )
    return lc

@pytest.fixture
def zenodo_protocol(request, zenodo_repository):
    """
    Sets a zenodo protocol to the test class
    """
    request.cls.protocol = ZenodoProtocol(zenodo_repository)


@pytest.fixture
def zenodo_repository(db, simple_logo):
    """
    A Zenodo repository
    """
    zenodo_oaisource = OaiSource.objects.get(
        identifier='zenodo'
    )
    repo = Repository.objects.create(
        api_key='secret_api_key',
        description='Zenodo Sandbox Repository - No papers will be deposited',
        endpoint='https://sandbox.zenodo.org/api/deposit/depositions',
        logo=simple_logo,
        name='Zenodo Sandbox',
        oaisource=zenodo_oaisource,
        protocol='ZenodoProtocol',
    )

    return repo
