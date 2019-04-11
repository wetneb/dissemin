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



from papers.tests.test_ajax import JsonRenderingTest
from papers.models import Paper

class PaperApiTest(JsonRenderingTest):

    def test_valid_doi(self):
        Paper.create_by_doi('10.1016/0379-6779(91)91572-r')
        self.checkJson(self.getPage('api-paper-doi',
                                    args=['10.1016/0379-6779(91)91572-r']))

    def test_valid_pk(self):
        paper = Paper.create_by_doi('10.1016/0379-6779(91)91572-r')
        self.checkJson(self.getPage('api-paper-pk',
                                    args=[paper.id]))

    def test_invalid_doi(self):
        self.checkJson(self.getPage('api-paper-doi',
                                    args=['10.10.10.10.10']), 404)

    def test_invalid_pk(self):
        self.checkJson(self.getPage('api-paper-pk',
                                    args=['999999999']), 404)

    def test_query(self):
        invalid_payloads = [
            'test', '{}',
            '{"doi":"anurisecbld"}',
            '{"title":""}',
            '{"title":"this is a test"}',
            '{"title":"this is a test","date":"aunriset"}',
            '{"title":"this is a test","date":"2008"}',
            '{"title":"this is a test","date":"2008","authors":"test"}',
            '{"title":"this is a test","date":"2008-03","authors":[]}',
            '{"title":"this is a test","date":"2008-03","authors":["lsc"]}',
            '{"title":"test","date":"2008-03","authors":[{"error":"test"}]}',
            ]

        for payload in invalid_payloads:
            self.checkJson(self.postPage('api-paper-query', postargs=payload,
                                         postkwargs={'content_type': 'application/json'}), 400)

        valid_payloads = [
            '{"title":"Strange resonances measured in Al+Al collisions at sqrt {S_ NN }= 2.65 GeV with the FOPI detector","date":"2015","authors":[{"plain":"Lopez, X."}]}',
            '{"doi":"10.1016/j.paid.2009.02.013"}',
                ]
        for payload in valid_payloads:
            self.checkJson(self.postPage('api-paper-query', postargs=payload,
                                         postkwargs={'content_type': 'application/json'}), 200)

    def test_bibtex_formatting(self):
        dois_bibtex = {
            '10.1007/978-3-662-49214-7_4': '''@incollection{Tang2016,
  author = {Tang, Ruiming and Amarilli, Antoine and Senellart, Pierre and Bressan, Stéphane},
  doi = {10.1007/978-3-662-49214-7_4},
  journal = {Lecture Notes in Computer Science},
  month = {jan},
  pages = {116-138},
  title = {A Framework for Sampling-Based XML Data Pricing},
  url = {https://doi.org/10.1007/978-3-662-49214-7_4},
  year = {2016}
}''',
            '10.1145/3034786.3056121': '''@misc{Amarilli2017,
  author = {Amarilli, Antoine and Monet, Mikaël and Senellart, Pierre},
  doi = {10.1145/3034786.3056121},
  journal = {Proceedings of the 36th ACM SIGMOD-SIGACT-SIGAI Symposium on Principles of Database Systems  - PODS '17},
  month = {jan},
  title = {Conjunctive Queries on Probabilistic Graphs: Combined Complexity},
  url = {https://doi.org/10.1145/3034786.3056121},
  year = {2017}
}''',
            '10.1007/978-3-319-45856-4_22': '''@incollection{Amarilli2016,
  author = {Amarilli, Antoine and Maniu, Silviu and Monet, Mikaël},
  doi = {10.1007/978-3-319-45856-4_22},
  journal = {Lecture Notes in Computer Science},
  month = {jan},
  pages = {323-330},
  title = {Challenges for Efficient Query Evaluation on Structured Probabilistic Data},
  url = {https://doi.org/10.1007/978-3-319-45856-4_22},
  year = {2016}
}''',
            '10.1103/physrevapplied.11.024003': '''@misc{Verney2019,
  author = {Verney, Lucas and Lescanne, Raphaël and Devoret, Michel H. and Leghtas, Zaki and Mirrahimi, Mazyar},
  doi = {10.1103/physrevapplied.11.024003},
  journal = {Physical Review Applied},
  month = {feb},
  title = {Structural Instability of Driven Josephson Circuits Prevented by an Inductive Shunt},
  url = {https://doi.org/10.1103/physrevapplied.11.024003},
  volume = {11},
  year = {2019}
}''',
        }
        for doi, bibtex in dois_bibtex.items():
            p = Paper.create_by_doi(doi)
            resp = self.getPage('api-paper-doi',
                                args=[doi], getargs={'format': 'bibtex'})

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.content.decode('utf-8').strip(),
                             bibtex.strip())

            resp = self.getPage('api-paper-pk',
                                args=[p.id], getargs={'format': 'bibtex'})

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.content.decode('utf-8').strip(),
                             bibtex.strip())
