# -*- encoding: utf-8 -*-
from __future__ import unicode_literals

# taken from https://www.caktusgroup.com/blog/2013/10/02/skipping-test-db-creation/

from django.test import TransactionTestCase
try:
    from django.test.runner import DiscoverRunner as BaseRunner
except ImportError:
    # Django < 1.6 fallback
    from django.test.simple import DjangoTestSuiteRunner as BaseRunner

from mock import patch


class NoDatabaseMixin(object):
    """
    Test runner mixin which skips the DB setup/teardown
    when there are no subclasses of TransactionTestCase to improve the speed
    of running the tests.
    """

    def build_suite(self, *args, **kwargs):
        """
        Check if any of the tests to run subclasses TransactionTestCase.
        """
        suite = super(NoDatabaseMixin, self).build_suite(*args, **kwargs)
        self._needs_db = any([isinstance(test, TransactionTestCase) for test in suite])
        return suite

    def setup_databases(self, *args, **kwargs):
        """
        Skip test creation if not needed. Ensure that touching the DB raises and
        error.
        """
        if self._needs_db:
            return super(NoDatabaseMixin, self).setup_databases(*args, **kwargs)
        if self.verbosity >= 1:
            print('No DB tests detected. Skipping Test DB creation...')
        self._db_patch = patch('django.db.backends.utils.CursorWrapper')
        self._db_mock = self._db_patch.start()
        self._db_mock.side_effect = RuntimeError('No testing the database!')
        return None

    def teardown_databases(self, *args, **kwargs):
        """
        Remove cursor patch.
        """
        if self._needs_db:
            return super(NoDatabaseMixin, self).teardown_databases(*args, **kwargs)
        self._db_patch.stop()
        return None


class FastTestRunner(NoDatabaseMixin, BaseRunner):
    """Actual test runner sub-class to make use of the mixin."""
