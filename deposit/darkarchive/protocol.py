from django.contrib.sites.models import Site

from deposit.darkarchive.forms import DarkArchiveForm
from deposit.protocol import RepositoryProtocol


class DarkArchiveProtocol(RepositoryProtocol):
    """
    A protocol that does does directly sends data to a repository, but to an intermediata database
    """

    # The class of the form the protocol uses
    form_class = DarkArchiveForm

    def __str__(self):
        """
        Return human readable class name
        """
        return "Dark Archive Protocol"


    def _get_authors(self):
        """
        Returns a list of authors, containing a dict with:
        first
        last
        orcid
        """
        authors = [
            {
                'first' : author['name']['first'],
                'last' : author['name']['last'],
                'orcid' : author['orcid'],
            }
            for author in self.paper.authors_list
        ]

        return authors


    def _get_depositor(self):
        """
        Returns a dictionary with first and last name
        """
        d = {
            'first' : self.user.first_name,
            'last' : self.user.last_name,
        }

        return d


    def _get_eissn(self):
        """
        Returns the eissn / essn if available or `None`
        """
        if self.publication.journal is not None:
            return self.publication.journal.essn


    def _get_embargo(self, form):
        """
        Takes the embargo date from the form and returns it as isoformatted string or None
        :param form: django form (BaseMetadataForm)
        :returns: string
        """
        embargo = form.cleaned_data.get('embargo', None)
        if embargo is not None:
            embargo = embargo.isoformat()
        return embargo


    def _get_issn(self):
        """
        Returns the issn if available or `None`
        """
        if self.publication.journal is not None:
            return self.publication.journal.issn


    def _get_license(self, license_chooser):
        """
        Returns a dictionary with fields about name, URI and transmit id
        """
        if license_chooser:
            d = {
                'name' : license_chooser.license.name,
                'uri' : license_chooser.license.uri,
                'transmit_id' : license_chooser.transmit_id
            }
            return d


    def _get_metadata(self, form, pdf):
        """
        Creates metadata ready to be converted into JSON.
        Mainly we create a dictionary with some types as content that serialize well into JSON
        """

        md = {
            'abstract' : form.cleaned_data.get('abstract', None),
            'authors' : self._get_authors(),
            'date' : self.paper.pubdate,
            'depositor' : {
                'first' : self.user.first_name,
                'last' : self.user.last_name,
                'email' : form.cleaned_data.get('email', None),
                'orcid' : self._get_depositor_orcid(),
                'is_contributor' : self.paper.is_owned_by(self.user, flexible=True),
            },
            'dissemin_id' : self.paper.pk,
            'doctype' : self.paper.doctype,
            'doi' : self.publication.doi,
            'eissn' : self._get_eissn(),
            'embargo' : self._get_embargo(form),
            'file_url' : 'https://{}{}'.format(Site.objects.get_current(), pdf.get_absolute_url()),
            'issn' : self._get_issn(),
            'issue' : self.publication.issue,
            'journal' : self.publication.full_journal_title(),
            'license' : self._get_license(form.cleaned_data.get('license', None)),
            'page' : self.publication.pages,
            'publisher' : self._get_publisher_name(),
            'sherpa_romeo_id' : self._get_sherpa_romeo_id(),
            'title' : self.paper.title,
            'volume' : self.publication.volume,
        }

        return md
