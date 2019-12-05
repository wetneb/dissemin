import pytest

from deposit.models import DepositRecord




@pytest.fixture
def deposit_record(request, db, book_god_of_the_labyrinth, authenticated_client, dummy_repository, uploaded_pdf):
    """
    A simple deposit record with all necessary data
    """
    dummy_repository.letter_declaration = 'test_pdf_generator'
    dummy_repository.save()
    dr = DepositRecord.objects.create(
        paper=book_god_of_the_labyrinth,
        user=authenticated_client.user,
        repository=dummy_repository,
        status='pending',
        file=uploaded_pdf,
    )

    request.cls.dr = dr
    request.cls.client = authenticated_client


@pytest.fixture
def dummy_deposit_record(book_god_of_the_labyrinth, user_leibniz, dummy_repository, uploaded_pdf):
    """
    Dummy deposit record with minimal information
    """

    dr = DepositRecord.objects.create(
        paper=book_god_of_the_labyrinth,
        user=user_leibniz,
        repository=dummy_repository,
        file=uploaded_pdf
    )

    return dr
