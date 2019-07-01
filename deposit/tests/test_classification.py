from deposit.models import ClassificationSubject
from deposit.models import ClassificationSystem

class TestClassficicationSubject():
    """
    Test class that contains tests for classification subjects
    """
    @staticmethod
    def test_str(dummy_repository, load_json):
        classification_system = load_json.load_classification_system('ddc', dummy_repository)
        number = "999"
        name = "Extraterrestrial worlds"
        s = ClassificationSubject.objects.create(number=number, name=name, transmit_id="not important", classification_system=classification_system)
        assert s.__str__() == number + " - " + name


class TestClassficicationSystem():
    """
    Test class that contains test for classification systems
    """
    @staticmethod
    def test_str(dummy_repository):
        name = "Dewey Decimal Class"
        short = "ddc"
        s = ClassificationSystem.objects.create(name=name, short=short, repeatable=True, repository=dummy_repository)
        assert s.__str__() == name + " " + short
