import os
import pytest
import responses

from datetime import date
from datetime import datetime
from datetime import timedelta
from urllib.parse import parse_qs
from urllib.parse import urlparse


from django.conf import settings
from django.utils import timezone

from backend.citeproc import CiteprocError
from backend.citeproc import CiteprocAuthorError
from backend.citeproc import CiteprocContainerTitleError
from backend.citeproc import CiteprocDateError
from backend.citeproc import CiteprocDOIError
from backend.citeproc import CiteprocPubtypeError
from backend.citeproc import CiteprocTitleError
from backend.citeproc import Citeproc
from backend.citeproc import CrossRef
from backend.citeproc import DOIResolver
from papers.baremodels import BareName
from papers.doi import doi_to_crossref_identifier
from papers.doi import doi_to_url
from papers.models import OaiRecord
from papers.models import OaiSource
from papers.models import Paper
from publishers.models import Journal
from publishers.models import Publisher


convert_to_name_pair_list = [
    ({'family': 'Farge', 'given': 'Marie'}, ('Marie', 'Farge')),
    ({'literal': 'Marie Farge'}, ('Marie', 'Farge')),
    ({'literal': 'Farge, Marie'}, ('Marie', 'Farge')),
    ({'family': 'Arvind'}, ('', 'Arvind')),
]

is_oai_license_params = [
    # CC
    ('http://creativecommons.org/licenses/by-nc-nd/2.5/co/', True),
    ('http://creativecommons.org/licenses/by-nc/3.10/', True),
    ('https://creativecommons.org/licenses/by-nc-sa/4.0/', True),
    # Other open license
    ('http://www.elsevier.com/open-access/userlicense/1.0/', True),
    # Closed license
    ('http://link.aps.org/licenses/aps-default-license', False),
    ('http://www.acs.org/content/acs/en/copyright.html', False),
    ('http://www.elsevier.com/tdm/userlicense/1.0/', False),
]


class TestCiteproc():
    """
    This class groups tests about the Citeproc class
    """

    test_class = Citeproc


    @pytest.mark.parametrize('url, expected', is_oai_license_params)
    def test_is_oa_license(self, url, expected):
        assert self.test_class.is_oa_license(url) == expected

    @pytest.mark.usefixtures('db')
    def test_to_paper(self, container_title, title, citeproc):
        p = self.test_class.to_paper(citeproc)
        # Ensure that paper is in database (i.e. created)
        assert p.pk >= 1
        # Check paper fields
        for author_p, author_c in zip(p.authors_list, citeproc['author']):
            assert author_p['name']['first'] == author_c['given']
            assert author_p['name']['last'] == author_c['family']
            assert author_p['affiliation'] == author_c['affiliation'][0]['name']
            assert author_p['orcid'] == author_c['ORCID']
        assert p.pubdate == date(*citeproc['issued']['date-parts'][0])
        assert p.title == title
        # Ensure that oairecord is in database (i.e. created)
        r = OaiRecord.objects.get(about=p)
        # Check oairecord fields
        assert r.doi == citeproc['DOI']
        assert r.identifier == doi_to_crossref_identifier(citeproc['DOI'])
        assert r.issue == citeproc['issue']
        assert r.journal_title == container_title
        assert r.pages == citeproc['page']
        assert r.pubdate == date(*citeproc['issued']['date-parts'][0])
        assert r.publisher_name == citeproc['publisher']
        assert r.source == OaiSource.objects.get(identifier='crossref')
        assert r.splash_url == doi_to_url(citeproc['DOI'])
        assert r.volume == citeproc['volume']


    @pytest.mark.parametrize('mock_function', ['_get_oairecord_data', '_get_paper_data'])
    def test_to_paper_invalid_data(self, monkeypatch, mock_function, citeproc):
        """
        If data is invalid, i.e. metadata is corrupted, somethings missing or so, must raise exception
        """
        def raise_citeproc_error(*args, **kwargs):
            raise CiteprocError
        monkeypatch.setattr(self.test_class, mock_function, raise_citeproc_error)
        with pytest.raises(CiteprocError):
            self.test_class.to_paper(citeproc)

    def test_to_paper_no_data(self):
        """
        If no data, must raise CiteprocError
        """
        with pytest.raises(CiteprocError):
            self.test_class.to_paper(None)


    @pytest.mark.parametrize('name, expected', convert_to_name_pair_list)
    def test_convert_to_name_pair(self, name, expected):
        """
        Test if name pairing works
        """
        assert self.test_class._convert_to_name_pair(name) == expected


    @pytest.mark.parametrize('author_elem, expected', [(dict(), None), ({'affiliation' : [{'name' : 'Porto'}]}, 'Porto'), ({'affiliation' : [{'name' : 'Porto'}, {'name' : 'Lissabon'}]}, 'Porto')])
    def test_get_affiliation(self, author_elem, expected):
        """
        Must return the first affiliation if any
        """
        assert self.test_class._get_affiliation(author_elem) == expected


    def test_get_abstract(self, citeproc):
        """
        Abstract must be set
        """
        assert self.test_class._get_abstract(citeproc) == citeproc['abstract']

    def test_get_abstact_missing(self, citeproc):
        """
        If no abstract, assert blank
        """
        del citeproc['abstract']
        assert self.test_class._get_abstract(citeproc) == ''

    def test_get_abstract_escaping(self, citeproc):
        """
        Must do some escaping, e.g. we sometimes get some jats tags
        """
        # We wrap the current abstract into some jats
        expected = citeproc['abstract']
        citeproc['abstract'] = r'<jats:p>{}<\/jats:p>'.format(expected)
        assert self.test_class._get_abstract(citeproc) == expected

    def test_get_affiliations(self, affiliations, citeproc):
        """
        Must have the same length as citeproc['author'] and identical to list of affiliations
        """
        r = self.test_class._get_affiliations(citeproc)
        assert len(r) == len(citeproc.get('author'))
        assert r == affiliations

    def test_get_affiliations_no_authors(self, citeproc):
        """
        Must rais exception
        """
        del citeproc['author']
        with pytest.raises(CiteprocAuthorError):
            self.test_class._get_affiliations(citeproc)


    def test_get_authors(self, citeproc):
        """
        The list of authors shall be a list of BareNames
        """
        r = self.test_class._get_authors(citeproc)
        assert isinstance(r, list)
        for barename in r:
            assert isinstance(barename, BareName)

    def test_get_authors_empty_list(self, citeproc):
        """
        The list of authors must not be empty
        """
        citeproc['author'] = []
        with pytest.raises(CiteprocAuthorError):
            self.test_class._get_authors(citeproc)

    def test_get_authors_no_list(self, citeproc):
        """
        author in citeproc must be a list
        """
        del citeproc['author']
        with pytest.raises(CiteprocAuthorError):
            self.test_class._get_authors(citeproc)

    def test_get_authors_invalid_author(self, monkeypatch, citeproc):
        """
        If 'None' is an entry, raise exception
        """
        # We mock the function and let it return None, so that name_pairs is a list of None
        monkeypatch.setattr(self.test_class, '_convert_to_name_pair', lambda x: None)
        with pytest.raises(CiteprocAuthorError):
            self.test_class._get_authors(citeproc)


    def test_get_container(self, container_title, citeproc):
        """
        Must return container title
        """
        assert self.test_class._get_container(citeproc) == container_title

    def test_get_container_missing(self):
        """
        Must return exception
        """
        with pytest.raises(CiteprocContainerTitleError):
            self.test_class._get_container(dict())


    def test_get_doi(self, citeproc):
        """
        Must return the DOI
        """
        assert self.test_class._get_doi(citeproc) == citeproc['DOI']

    def test_get_doi_invalid(self):
        """
        Must raise exception
        """
        with pytest.raises(CiteprocDOIError):
            self.test_class._get_doi({'DOI' : 'spanish inquisition'})

    def test_get_doi_missing(self):
        """
        Must raise exception
        """
        with pytest.raises(CiteprocDOIError):
            self.test_class._get_doi(dict())


    @pytest.mark.parametrize('issn, expected', [('1234-5675', '1234-5675'), (['1234-5675', ], '1234-5675'), ([], '')])
    def test_get_issn(self, citeproc, issn, expected):
        """
        Must return the issn or ''
        """
        citeproc['ISSN'] = issn
        assert self.test_class._get_issn(citeproc) == expected

    def test_get_issn_missing(self, citeproc):
        """
        Must return ''
        """
        del citeproc['ISSN']
        assert self.test_class._get_issn(citeproc) == ''


    @pytest.mark.usefixtures('db', 'mock_alias_publisher_increment', 'mock_journal_find', 'mock_publisher_find')
    @pytest.mark.parametrize('journal', [Journal(publisher=Publisher()), None])
    def test_get_oairecord_data(self, monkeypatch, container_title, issn, citeproc, journal):
        """
        We do some assertions on the results, but relatively lax, as we test the called functions, too
        """
        monkeypatch.setattr(Journal, 'find', lambda issn, title: journal)
        r = self.test_class._get_oairecord_data(citeproc)
        assert r['doi'] == citeproc['DOI']
        assert r['description'] == citeproc['abstract']
        assert r['identifier'] == doi_to_crossref_identifier(citeproc['DOI'])
        assert r['issn'] == issn
        assert r['issue'] == citeproc['issue']
        assert r['journal'] == journal
        assert r['journal_title'] == container_title
        assert r['pages'] == citeproc['page']
        assert r['pdf_url'] == '' # Is not OA
        assert r['pubdate'] == date(*citeproc['issued']['date-parts'][0])
        assert r['publisher_name'] == citeproc['publisher']
        assert r['pubtype'] == citeproc['type']
        assert r['source'] == OaiSource.objects.get(identifier='crossref')
        assert r['splash_url'] == doi_to_url(citeproc['DOI'])
        assert r['volume'] == citeproc['volume']

    @pytest.mark.usefixtures('db', 'mock_journal_find', 'mock_publisher_find')
    def test_get_oairecord_data_missing(self, monkeypatch, container_title, issn, citeproc):
        """
        Some fields may be empty, namely those with a direct get call
        """
        keys = ['abstract', 'issue', 'publisher', 'page', 'volume']
        for k in keys:
            del citeproc[k]
        r = self.test_class._get_oairecord_data(citeproc)
        keys = ['description', 'issue', 'publisher_name', 'pages', 'volume']
        for k in keys:
            assert r[k] == ''


    @pytest.mark.parametrize('orcid, expected', [({'ORCID' : '0000-0001-8187-9704'}, '0000-0001-8187-9704'), ({'ORCID' : '0000-0001-8187-9705'}, None), ({}, None)])
    def test_get_orcid(self, orcid, expected):
        """
        Must be valid or None
        """
        assert self.test_class._get_orcid(orcid) == expected

    def test_get_orcids(self, orcids, citeproc):
        """
        Must have the same length as citeproc['author'] and identical to list of  orcid
        """
        r = self.test_class._get_orcids(citeproc)
        assert len(r) == len(citeproc.get('author'))
        assert r == orcids

    def test_get_orcid_no_authors(self, citeproc):
        """
        Must rais exception
        """
        del citeproc['author']
        with pytest.raises(CiteprocAuthorError):
            self.test_class._get_orcids(citeproc)


    def test_get_paper_data(self, affiliations, orcids, title, citeproc):
        """
        We do some assertions on the results, but relatively lax, as we test the called functions, too
        """
        r = self.test_class._get_paper_data(citeproc)
        assert r['affiliations'] == affiliations
        for a in r['author_names']:
            assert isinstance(a, BareName)
        assert r['orcids'] == orcids
        assert r['pubdate'] == date(*citeproc['issued']['date-parts'][0])
        assert r['title'] == title


    @pytest.mark.parametrize('doi', [True, False])
    @pytest.mark.parametrize('license', [True, False])
    def test_get_pdf_url(self, monkeypatch, doi, license):
        """
        Must return true or false
        """
        monkeypatch.setattr(self.test_class, '_is_oa_by_doi', lambda x: doi)
        monkeypatch.setattr(self.test_class, '_is_oa_by_license', lambda x: license)
        url = 'https://repository.dissem.in/entry/3242/document.pdf'
        r = self.test_class._get_pdf_url(doi, license, url)
        if doi or license:
            assert r == url
        else:
            assert r == ''


    def test_get_pubdate_issued(self, citeproc):
        """
        If contains issued, take this
        """
        citeproc['created'] = {'date-parts' : [[2019, 10, 11]]}
        citeproc['deposited'] = {'date-parts' : [[2019, 10, 12]]}
        assert self.test_class._get_pubdate(citeproc) == date(*citeproc['issued']['date-parts'][0])

    def test_get_pubdate_created(self, citeproc):
        """
        If contains no issued, take created
        """
        del citeproc['issued']
        citeproc['created'] = {'date-parts' : [[2019, 10, 11]]}
        citeproc['deposited'] = {'date-parts' : [[2019, 10, 12]]}
        assert self.test_class._get_pubdate(citeproc) == date(*citeproc['created']['date-parts'][0])

    def test_get_pubdate_deposited(self, citeproc):
        """
        If contains no issued and created, take deposited
        """
        del citeproc['issued']
        citeproc['deposited'] = {'date-parts' : [[2019, 10, 12]]}
        assert self.test_class._get_pubdate(citeproc) == date(*citeproc['deposited']['date-parts'][0])

    def test_get_pubdate_no_date(self, citeproc):
        """
        If contains no date, raise exception
        """
        del citeproc['issued']
        with pytest.raises(CiteprocDateError):
            self.test_class._get_pubdate(citeproc)

    def test_get_pubdate_received_none(self, monkeypatch):
        """
        If no valid date is found, raise exception
        """
        monkeypatch.setattr(self.test_class, '_parse_date', lambda x: None)
        with pytest.raises(CiteprocDateError):
            self.test_class._get_pubdate(dict())


    @pytest.mark.usefixtures('mock_alias_publisher_increment')
    def test_get_publisher_by_journal(self):
        """
        Must return Publisher object
        """
        publisher = Publisher()
        journal = Journal(
            publisher=publisher
        )
        assert self.test_class._get_publisher('p_name', journal) == publisher

    def test_get_publisher_by_name(self, monkeypatch):
        """
        Must return publisher object
        """
        publisher = Publisher()
        monkeypatch.setattr(Publisher, 'find', lambda x: publisher)
        assert self.test_class._get_publisher('p_name', None) == publisher


    def test_get_pubtype(self):
        """
        Must return something from PAPER_TYPES
        """
        pubtype = 'book'
        assert self.test_class._get_pubtype({'type' : pubtype}) == pubtype

    def test_get_pubtype_strange(self):
        """
        Must return other
        """
        assert self.test_class._get_pubtype({'type' : 'spanish inquisition'}) == 'other'

    def test_get_pubtype_missing(self):
        """
        Must raise exception
        """
        with pytest.raises(CiteprocPubtypeError):
            self.test_class._get_pubtype(dict())

    def test_get_title(self, citeproc):
        r = self.test_class._get_title(citeproc)
        assert r == citeproc['title'][:1024]
        assert len(r) <= 1024

    def test_get_title_length(self, citeproc):
        """
        Title must no be longer than 1024 chars
        """
        citeproc['title'] = 'x' * 2000
        r = self.test_class._get_title(citeproc)
        assert r == citeproc['title'][:1024]
        assert len(r) <= 1024

    def test_get_title_length_with_unicode(self, citeproc):
        citeproc['title'] = '–' * 1024
        r = self.test_class._get_title(citeproc)
        assert r == citeproc['title'][:341]
        assert len(r) <= 1024

    def test_get_title_no_title(self, citeproc):
        """
        Title is mandatory
        """
        del citeproc['title']
        with pytest.raises(CiteprocTitleError):
            self.test_class._get_title(citeproc)

    def test_get_title_emtpy_string(self, citeproc):
        """
        If no title is found, expect CiteprocTitleError
        """
        citeproc['title'] = ''
        with pytest.raises(CiteprocTitleError):
            self.test_class._get_title(citeproc)


    @pytest.mark.parametrize('doi, expected', [('10.2195/spam', True), ('10.15122/spam', False)])
    def test_is_oa_by_doi(self, doi, expected):
        """
        Must be true or false
        """
        assert self.test_class._is_oa_by_doi(doi) == expected

    @pytest.mark.parametrize('licenses, expected', [([{'URL' : 'creativecommons.org/licenses/'}], True), ([{'URL' : 'https://dissem.in/not_free'}], False), ([{}], False), ([], False)])
    def test_is_oa_by_license(self, licenses, expected):
        """
        Must be true or false
        """
        assert self.test_class._is_oa_by_license(licenses) == expected


    @pytest.mark.parametrize('data, expected', [({'date-parts' : [[2019, 10, 10]]}, date(2019, 10, 10)), ({'raw' : '2019-10-10'}, date(2019, 10, 10)), (None, None), ({'spam' : 'ham'}, None)])
    def test_parse_date(self, data, expected):
        """
        Must return a valid date or None
        """
        assert self.test_class._parse_date(data) == expected



    @pytest.mark.parametrize('date_parts, expected', [([2019, ], date(2019, 1, 1)), ([2019, 10, ], date(2019, 10, 1)), ([2019, 10, 10], date(2019, 10, 10))])
    def test_parse_date_parts(self, date_parts, expected):
        """
        Must parse the date list
        """
        assert self.test_class._parse_date_parts(date_parts) == expected




class TestCrossRef(TestCiteproc):
    """
    This class groups tests about the CrossRef class
    """

    test_class = CrossRef

    @pytest.fixture
    def citeproc(self, container_title, title, citeproc):
        """
        In general, the CrossRef is identical to citeproc, but there are some differences.
        We change the fixture accordingly
        title is a list
        container-title is a list
        """
        citeproc['title'] = [title, ]
        citeproc['container-title'] = [container_title, ]

        return citeproc


    @pytest.mark.usefixtures('db')
    def test_fetch_latest_records(self, monkeypatch):
        """
        Essentially, we test if source date is updated
        """
        def ret_func(day):
            # Datetime objects are date objects
            assert isinstance(day, date)
            assert not isinstance(day, datetime)
            return None

        monkeypatch.setattr(self.test_class, '_fetch_day', ret_func)

        source = OaiSource.objects.get(identifier='crossref')
        # For some reason, last_update ist not 1970
        source.last_update = timezone.now() - timedelta(days=10)
        source.save()
        self.test_class.fetch_latest_records()
        source.refresh_from_db()
        assert source.last_update.date() == timezone.now().date() - timedelta(days=1)

    @responses.activate
    @pytest.mark.usefixtures('db')
    def test_fetch_batch(self):
        dois = ['10.1016/j.gsd.2018.08.007', '10.1109/sYnAsc.2010.88']
        f_path = os.path.join(settings.BASE_DIR, 'backend', 'tests', 'data', 'crossref_batch.json')
        with open(f_path, 'r') as f:
            body = f.read()
        responses.add(
            responses.GET,
            url='https://api.crossref.org/works',
            body=body,
            status=200,
        )

        papers = self.test_class.fetch_batch(dois)
        called_url = responses.calls[0].request.url
        query = parse_qs(urlparse(called_url).query)
        query_f = query['filter'][0].split(',')
        for doi, filter_doi in zip(dois, query_f):
            assert doi == filter_doi.split(':')[1]
        for paper in papers:
            assert isinstance(paper, Paper)
        for paper, doi in zip(papers, dois):
            assert paper.get_doi() == doi.lower()

    @responses.activate
    @pytest.mark.usefixtures('db')
    def test_fetch_batch_doi_not_found(self):
        """
        If doi is not in result list, entry must be none
        """
        f_path = os.path.join(settings.BASE_DIR, 'backend', 'tests', 'data', 'crossref_batch.json')
        with open(f_path, 'r') as f:
            body = f.read()
        responses.add(
            responses.GET,
            url='https://api.crossref.org/works',
            body=body,
            status=200,
        )
        dois = ['10.1016/j.gsd.2018.08.007', '10.1109/sYnAsc.2010.88']
        doi_invalid = '10.spanish/inquisition'
        dois.append(doi_invalid)
        papers = self.test_class.fetch_batch(dois)
        assert papers[2] is None

    @responses.activate
    @pytest.mark.usefixtures('db')
    def test_fetch_batch_doi_with_comma(self):
        """
        If doi has comma, entry must be none
        """
        f_path = os.path.join(settings.BASE_DIR, 'backend', 'tests', 'data', 'crossref_batch.json')
        with open(f_path, 'r') as f:
            body = f.read()
        responses.add(
            responses.GET,
            url='https://api.crossref.org/works',
            body=body,
            status=200,
        )
        dois = ['10.1016/j.gsd.2018.08.007', '10.1109/sYnAsc.2010.88']
        doi_comma= '10.spanish,inquisition'
        dois.append(doi_comma)
        papers = self.test_class.fetch_batch(dois)
        assert papers[2] is None

    @pytest.mark.usefixtures('db', 'mock_crossref')
    def test_fetch_batch_doi_with_backslash(self):
        """
        CrossRef just drops backslash in search, so that such a DOI is not present in return list, while ingested correctly into the system
        """
        dois = [r'10.1007/978-3-319-66824-6\_35']
        r = self.test_class.fetch_batch(dois)
        assert isinstance(r[0], Paper)

    @pytest.mark.usefixtures('db')
    def test_fetch_day(self, rsps_fetch_day):
        """
        Here we imitate the CrossRef API in a very simple version.
        We mock the request and inspect the params.
        Then we return a result that we have gotten from CrossRef
        """
        self.test_class.rows = 30
        self.test_class.emit_status_every = 3

        day = date.today()
        self.test_class._fetch_day(day)
        # Some assertions
        called_url = rsps_fetch_day.calls[0].request.url
        query = parse_qs(urlparse(called_url).query)
        query_f = query['filter'][0].split(',')
        for date_filter in ['from-update-date', 'until-update-date']:
            assert date_filter + ':{}'.format(day) in query_f
        assert query['rows'][0] == str(self.test_class.rows)
        assert query['mailto'][0] == settings.CROSSREF_MAILTO

    @pytest.mark.usefixtures('db')
    def test_fetch_day_citeproc_error(self, monkeypatch, rsps_fetch_day):
        """
        If a CiteprocError raises, do not starve
        """
        def callback(*args, **kwargs):
            raise CiteprocError('Error')
        monkeypatch.setattr(self.test_class, 'to_paper', callback)
        day = date.today()
        self.test_class._fetch_day(day)

    @pytest.mark.usefixtures('db')
    def test_fetch_day_value_error(self, monkeypatch, rsps_fetch_day):
        """
        If a ValueError raises, do not starve
        """
        def callback(*args, **kwargs):
            raise ValueError('Error')
        monkeypatch.setattr(self.test_class, 'to_paper', callback)
        day = date.today()
        self.test_class._fetch_day(day)


    def test_filter_dois_by_comma(self):
        """
        Tests filtering of DOIs wheter they have a ',' or not
        """
        doi = '10.a'
        doi_comma = '10.a,b'
        dois = [doi, doi_comma]
        assert self.test_class._filter_dois_by_comma(dois) == [doi]


    def test_get_title(self, citeproc):
        """
        CrossRef does serve the title in a list
        """
        r = self.test_class._get_title(citeproc)
        assert r == citeproc.get('title')[:1024]
        assert len(r) <= 1024

    def test_get_title_length(self, citeproc):
        """
        CrossRef does serve the title in a list. Must not be longer than 1024 chars
        """
        citeproc['title'] = ['x' * 2000, ]
        r = self.test_class._get_title(citeproc)
        assert r == citeproc.get('title')[:1024]
        assert len(r) <= 1024

    def test_get_title_list_error(self, citeproc):
        """
        CrossRef does serve the title in a list
        List must not be non-empty
        """
        citeproc['title'] = list()
        with pytest.raises(CiteprocTitleError):
            self.test_class._get_title(citeproc)

    def test_get_title_emtpy_string(self, citeproc):
        """
        If no title is found, expect CiteprocTitleError
        """
        citeproc['title'] = ['',]
        with pytest.raises(CiteprocTitleError):
            self.test_class._get_title(citeproc)


    def test_remove_unapproved_characters(self):
        """
        Must return only keep "a-z", "A-Z", "0-9" and "-._;()/"
        """
        assert self.test_class.remove_unapproved_characters(r'10.1007/978-3-319-66824-6\_35') == '10.1007/978-3-319-66824-6_35'


class TestDOI(TestCiteproc):
    """
    This class groups tests about the DOI class
    """

    test_class = DOIResolver

    @pytest.mark.usefixtures('db')
    @pytest.mark.parametrize('doi', ['10.1016/j.gsd.2018.08.007', '10.1109/sYnAsc.2010.88'])
    def test_save_doi(self, mock_doi, doi):
        """
        Must save the paper
        """
        p = self.test_class.save_doi(doi)
        # Header must be set
        assert mock_doi.calls[0].request.headers.get('Accept') == 'application/citeproc+json'
        # Check if paper is created
        assert p.pk >= 1
        r = OaiRecord.objects.get(about=p)
        assert r.journal_title != ''
        assert r.publisher_name != ''


    @pytest.mark.usefixtures('db')
    def test_save_doi_existing(self, mock_doi):
        """
        If DOI is already in system, expect not a new paper, but the one from the database
        """
        doi = '10.1016/j.gsd.2018.08.007'
        p = self.test_class.save_doi(doi)
        q = self.test_class.save_doi(doi)

        assert p == q
