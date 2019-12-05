import pytest

from deposit.darkarchive.protocol import DarkArchiveProtocol
from deposit.models import Repository


@pytest.fixture
def dark_archive_repository(simple_logo, oaisource):
    """
    Returns a repository for dark archive tests
    """
    repository = Repository.objects.create(
        name='Dark Archivce Test Repository',
        description='Dark archive test repository',
        logo=simple_logo,
        protocol='DarkArchive',
        oaisource=oaisource.dummy_oaisource(),
    )

    return repository


@pytest.fixture
def dark_archive_protocol(request, dark_archive_repository):
    """
    Sets the dark archive protocol as protocol to be used
    """
    request.cls.protocol = DarkArchiveProtocol(dark_archive_repository)
