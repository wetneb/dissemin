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


from __future__ import unicode_literals

import unittest

from papers.orcid import OrcidProfile


class OrcidProfileTest(unittest.TestCase):

    @classmethod
    def setUpClass(self):
        self.antonin = OrcidProfile(orcid_id='0000-0002-8612-8827')
        self.thomas = OrcidProfile(orcid_id='0000-0003-0524-631X')
        self.sergey = OrcidProfile(orcid_id='0000-0003-3397-9895')

    def test_simple_name(self):
        self.assertEqual(self.antonin.name, ('Antonin', 'Delpeuch'))
        self.assertEqual(self.thomas.name, ('Thomas', 'Bourgeat'))

    def test_credit_name(self):
        self.assertEqual(self.sergey.name, ('Sergey M.', 'Natanzon'))
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0001-9547-293X').name, ('Darío', 'Álvarez'))

    def test_empty_lastname(self):
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0001-5006-3868').name, ('Qiang', ''))

    def test_other_names(self):
        self.assertEqual(set(self.sergey.other_names),
                         set([('Sergey', 'Natanzon'), ('S.', 'Natanzon'),
                              ('S. M.', 'Natanzon'), ('Sergey', 'Natanzon')]))

    def test_homepage_without_http(self):
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0002-5710-3989').homepage, 'http://evrard.perso.enseeiht.fr')

    def test_iterable(self):
        for key in self.thomas:
            self.assertEqual(type(key), unicode)

    def test_attr(self):
        self.assertTrue('orcid-profile' in self.thomas)
        self.assertEqual(type(self.thomas['orcid-profile']), dict)

    def test_wrong_instance(self):
        with self.assertRaises(ValueError):
            p = OrcidProfile()
            p.fetch('0000-0002-2963-7764', 'dissem.in')

    def test_sandbox(self):
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0002-5654-4053').name, ('Peter', 'Lieth'))

    def test_search(self):
        # for this one we use the production database
        # because test profiles on the sandbox
        # tend to get deleted quite often
        results = list(OrcidProfile.search_by_name('John', 'Doe'))
        self.assertTrue(all(map(lambda x: len(x['orcid']) and (
            len(x['first']) or len(x['last'])), results)))
        names_returned = map(lambda x: (x['first'], x['last']), results)
        self.assertTrue(('John', 'Doe') in names_returned)

    def test_institution(self):
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0002-0022-2290').institution,
            {'name':'Ecole Normale Superieure',
             'identifier':None,
             'country':'FR'})
        self.assertEqual(OrcidProfile(
            orcid_id='0000-0002-5654-4053').institution,
            {'country': 'FR',
             'identifier': None,
             'name': "Polytech'Rambouillet"})

