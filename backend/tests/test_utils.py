from datetime import timedelta
from time import sleep

from backend.utils import group_by_batches
from backend.utils import report_speed
from backend.utils import utf8_truncate
from backend.utils import with_speed_report


def test_group_by_batches():
    assert list(group_by_batches(range(10), batch_size=4)) == [[0,1,2,3],[4,5,6,7],[8,9]]


def test_report_speed():
    assert list(with_speed_report(range(10))) == list(range(10))
    assert list(with_speed_report([])) == []

    @report_speed(name='my_generator', report_delay=timedelta(seconds=0.1))
    def second_generator(limit):
        for elem in range(limit):
            sleep(0.01)
            yield elem

    assert list(second_generator(20)) == list(range(20))


class TestUtf8Truncate:
    """
    Tests truncation by utf-8 length
    """

    def test_utf8_truncate_ascii(self):
        assert utf8_truncate('x' * 1026) == 'x' * 1024

    def test_utf8_truncate_unicode(self):
        assert utf8_truncate('–' * 1024) == '–' * 341