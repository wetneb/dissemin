import copy
import langdetect
import requests
import logging

from io import BytesIO
from lxml import etree
from zipfile import ZipFile

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import MultipleObjectsReturned
from django.utils.translation import ugettext as _

from deposit.models import UserPreferences
from deposit.protocol import DepositError
from deposit.protocol import DepositResult
from deposit.protocol import RepositoryProtocol
from deposit.registry import protocol_registry
from deposit.sword.forms import SWORDMETSForm

from papers.models import Researcher

logger = logging.getLogger('dissemin.' + __name__)
        
        
# Namespaces
DISSEMIN_NAMESPACE = "https://dissem.in/deposit/terms/"
METS_NAMESPACE = "http://www.loc.gov/METS/"
MODS_NAMESPACE = "http://www.loc.gov/mods/v3"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"

DS = "{%s}" % DISSEMIN_NAMESPACE
METS = "{%s}" % METS_NAMESPACE
MODS = "{%s}" % MODS_NAMESPACE
XLINK = "{%s}" % XLINK_NAMESPACE

NSMAP = {
    'mets' : METS_NAMESPACE,
    'ds' : DISSEMIN_NAMESPACE,
    'xlink' : XLINK_NAMESPACE,
    'xsi' : XSI_NAMESPACE
}


class SWORDMETSProtocol(RepositoryProtocol):
    """
    A protocol that performs a deposito via SWORDv2 using a METS Container.
    """

    # The class of the form for the deposit
    form_class = SWORDMETSForm

    def _get_deposit_result(self, response):
        """
        Processes the deposit result as presented by sword.
        We try to set the splash url.
        We set deposit_status to pending.
        We do not set a pdf_url because we expect moderation, so a pdf_url would be a dead link (for samoe time).
        """
        try:
            sword_statement = etree.fromstring(bytes(response, encoding='utf-8'))
        except etree.XMLSyntaxError:
            self.log('Invalid XML response from {}'.format(self.repository.name))
            raise DepositError(_('The repository {} returned invalid XML').format(self.repository.name))

        original_deposit = sword_statement.find('.//sword:originalDeposit', namespaces=sword_statement.nsmap)

        if original_deposit is None:
            splash_url = None
        else:
            splash_url = original_deposit.get('href', None)
        if splash_url is not None:
            identifier = splash_url.split('/')[-1]
        else:
            identifier = None
            msg = 'Found no splash url in XML reposonse from repository {}. Either no originalDeposit was present or the href was missing.'.format(self.repository.name)
            self.log(msg)
            logger.warning(msg)

        # We expect that SWORD Repos usually have moderation. If this is at some point not the case, we can make this more flexible
        status = 'pending'

        deposit_result = DepositResult(identifier=identifier, splash_url=splash_url, status=status)

        return deposit_result


    def _get_mets(self, metadata, dissemin_metadata):
        """
        Creates a mets xml from metadata
        Policy for creation is: One-time-usage, so keep the document as small as possible. This means
            * Attributes and elements are omitted if not needed
            * There is one and only one dmdSec
            * MDTYPE in dmdSec/mdWrap is always `OTHER`
            * One and only file that is named `document.pdf`

        :params metadata: Bibliographic metadata as lxml etree
        :params dissemin_metadata: Dissemin metadata as lxml etree
        :returns: complete mets as string
        """

        # Creation of document root
        mets_xml = etree.Element(METS + 'mets', nsmap=self.NSMAP)

        # Creation of metsHdr
        # We use this to make the mets itself distingushable from e.g. DeppGreen
        mets_hdr = etree.SubElement(mets_xml, METS + 'metsHdr')
        mets_agent = etree.SubElement(mets_hdr, METS + 'agent', ROLE='CREATOR', TYPE='ORGANIZATION')
        mets_name = etree.SubElement(mets_agent, METS + 'name')
        mets_name.text = 'Dissemin'

        # Creation of dmdSec and insertion of metadata
        mets_dmdSec = etree.SubElement(mets_xml, METS + 'dmdSec', ID='d_dmd_1')
        mets_mdWrap = etree.SubElement(mets_dmdSec, METS + 'mdWrap', MDTYPE='OTHER')
        mets_xmlData = etree.SubElement(mets_mdWrap, METS + 'xmlData')
        mets_xmlData.insert(0, metadata)

        # Creation of amdSec and insertion of dissemin metada
        mets_amdSec = etree.SubElement(mets_xml, METS + 'amdSec', ID='d_amd_1')
        mets_rightsMD = etree.SubElement(mets_amdSec, METS + 'rightsMD', ID='d_rightsmd_1')
        mets_mdWrap = etree.SubElement(mets_rightsMD, METS + 'mdWrap', MDTYPE='OTHER')
        mets_xmlData = etree.SubElement(mets_mdWrap, METS + 'xmlData')
        mets_xmlData.insert(0, dissemin_metadata)

        # Creation of fileSec
        mets_fileSec = etree.SubElement(mets_xml, METS + 'fileSec')
        mets_fileGrp = etree.SubElement(mets_fileSec, METS + 'fileGrp')
        mets_file = etree.SubElement(mets_fileGrp, METS + 'file', ID='d_file_1')
        mets_FLocat = etree.SubElement(mets_file, METS + 'FLocat')
        mets_FLocat.set(XLINK + 'href', 'document.pdf')
        mets_FLocat.set('LOCTYPE', 'URL')

        # Creation of structMap
        mets_structMap = etree.SubElement(mets_xml, METS + 'structMap')
        mets_div_dmd = etree.SubElement(mets_structMap, METS + 'div', DMDID='d_dmd_1')
        mets_div_file = etree.SubElement(mets_div_dmd, METS + 'div')
        etree.SubElement(mets_div_file, METS + 'fptr', FILEID='d_file_1')

        return etree.tostring(mets_xml, pretty_print=True, encoding='utf-8', xml_declaration=True).decode()


    @staticmethod
    def _get_mets_container(pdf, mets):
        """
        Creates a mets package, i.e. zip for a given file and given schema. The filename in the package is taken from mets.

        :params pdf: A pdf file
        :params mets: A mets as lxml etree
        :returns: a zip object
        """
        s = BytesIO()
        with ZipFile(s, 'w') as zip_file:
            zip_file.write(pdf.absolute_path, 'document.pdf')
            zip_file.writestr('mets.xml', mets)
        return s


    def _get_xml_dissemin_metadata(self, form):
        """
        This returns the special dissemin metadata as lxml.
        Currently not all features are supported.
        :param form: form with user given data
        :returns: lxml object ready to inserted
        """

        ds = etree.Element(DS + 'dissemin')
        ds.set('version', '1.0')

        # Information about the depositor

        ds_depositor = etree.SubElement(ds, DS + 'depositor')

        ds_authentication = etree.SubElement(ds_depositor, DS + 'authentication')
        # hard-coded since there is currently only one authentication method
        ds_authentication.text = 'orcid'

        ds_first_name = etree.SubElement(ds_depositor, DS + 'firstName')
        ds_first_name.text = self.user.first_name
        ds_last_name = etree.SubElement(ds_depositor, DS + 'lastName')
        ds_last_name.text = self.user.last_name

        ds_email = etree.SubElement(ds_depositor, DS + 'email')
        ds_email.text = form.cleaned_data['email']

        orcid = self._get_depositor_orcid()

        if orcid is not None:
            ds_orcid = etree.SubElement(ds_depositor, DS + 'orcid')
            ds_orcid.text = orcid

        ds_is_contributor = etree.SubElement(ds_depositor, DS + 'isContributor')
        if self.paper.is_owned_by(self.user, flexible=True):
            ds_is_contributor.text = 'true'
        else:
            ds_is_contributor.text = 'false'

        # Information about the publication

        ds_publication = etree.SubElement(ds, DS + 'publication')

        license = form.cleaned_data.get('license', None)
        if license is not None:
            ds_license = etree.SubElement(ds_publication, DS + 'license')
            ds_license_name = etree.SubElement(ds_license, DS + 'licenseName')
            ds_license_name.text = license.license.name
            ds_license_uri = etree.SubElement(ds_license, DS + 'licenseURI')
            ds_license_uri.text = license.license.uri
            ds_license_transmit = etree.SubElement(ds_license, DS + 'licenseTransmitId')
            ds_license_transmit.text = license.transmit_id

        ds_dissemin = etree.SubElement(ds_publication, DS + 'disseminId')
        ds_dissemin.text = str(self.paper.pk)

        embargo = form.cleaned_data.get('embargo', None)
        if embargo is not None:
            ds_embargo = etree.SubElement(ds_publication, DS + 'embargoDate')
            ds_embargo.text = embargo.isoformat()

        romeo_id = self._get_sherpa_romeo_id()

        if romeo_id is not None:
            ds_romeo = etree.SubElement(ds_publication, DS + 'romeoId')
            ds_romeo.text = str(self.publication.publisher.romeo_id)

        return ds


    @staticmethod
    def _get_xml_metadata(form):
        """
        This function returns metadata as lxml etree object, that is ready to inserted into a mets.xml. Override this function in your subclassed protocol.
        """
        raise NotImplementedError("Function not implemented")


    def get_form_initial_data(self, **kwargs):
        """
        Calls super and returns form's initial values.
        """
        data = super().get_form_initial_data(**kwargs)

        # We try to find an email, if we do not succed, that's ok
        up = UserPreferences.get_by_user(user=self.user)
        if up.email:
            data['email'] = up.email
        else:
            try:
                r = Researcher.objects.get(user=self.user)
            except ObjectDoesNotExist:
                pass
            except MultipleObjectsReturned:
                logger.warning("User with id {} has multiple researcher objects assigned".format(self.user.id))
            else:
                if r.email:
                    data['email'] = r.email

        return data


    def submit_deposit(self, pdf, form):
        """
        Submit paper to the repository. This is a wrapper for the subclasses and calls some protocol specific functions. It creates the METS container and deposits.

        :param pdf: UploadedPDF object
        :param form: The form returned by get_form and completed by the user

        :returns: DepositResult object
        """

        # Raise error if login credentials are missing. These are not mandatory in Admin UI, since alternatively an API Key can be used, but not for SWORD
        if not (self.repository.username and self.repository.password):
            raise DepositError(_("Username or password not provided for this repository. Please contact the Dissemin team."))

        metadata = self._get_xml_metadata(form)
        dissemin_metadata = self._get_xml_dissemin_metadata(form)
        mets = self._get_mets(metadata, dissemin_metadata)
        # Logging Metadata
        self.log('Metadata looks like:')
        self.log(mets)

        zipfile = self._get_mets_container(pdf, mets)

        # Send request to repository
        self.log("### Preparing request to repository")

        auth = (self.repository.username, self.repository.password)
        headers = {
                'Content-Type': 'application/zip',
                'Content-Disposition': 'filename=mets.zip',
                'Packaging': 'http://purl.org/net/sword/package/METSMODS',
        }

        self.log("### Sending request")

        r = requests.post(self.repository.endpoint, auth=auth, headers=headers, data=zipfile.getvalue(), timeout=20)

        self.log_request(r, 201, _('Unable to deposit to repository') + self.repository.name) 

        #Deposit was successful

        self.log("This is what the repository yelled back:")
        self.log(r.text)

        deposit_result = self._get_deposit_result(r.text)

        # Set the license for the deposit result if delivered
        deposit_result = self._add_license_to_deposit_result(deposit_result, form)

        # Set the embargo_date for the deposit result if delivered
        deposit_result = self._add_embargo_date_to_deposit_result(deposit_result, form)

        return deposit_result


class SWORDMETSMODSProtocol(SWORDMETSProtocol):
    """
    Protocol that implements MODS metadata with SWORDMETSProtocol
    """

    # We copy the namespace and add MODS namespace, to have all namespaces in METS root element
    NSMAP = copy.copy(NSMAP)
    NSMAP['mods'] = MODS_NAMESPACE


    def __str__(self):
        """
        Return human readable class name
        """
        return "SWORD Protocol (MODS)"


    def _get_xml_metadata(self, form):
        """
        Creates metadata as lxml etree in MODS
        """
        self.log("### Creating MODS metadata from publication and form")

        # Creation of root
        mods_xml = etree.Element(MODS + 'mods')
        mods_xml.set('version', '3.7')

        # Abstract
        if form.cleaned_data['abstract']:
            mods_abstract = etree.SubElement(mods_xml, MODS + 'abstract')
            mods_abstract.text = form.cleaned_data['abstract']

        # Date
        mods_origin_info = etree.SubElement(mods_xml, MODS + 'originInfo')
        mods_date_issued = etree.SubElement(mods_origin_info, MODS + 'dateIssued')
        mods_date_issued.set('encoding', 'w3cdtf')
        mods_date_issued.text = str(self.paper.pubdate)

        # Identifier / DOI and relatedItem
        if self.publication:
            # DOI
            if self.publication.doi:
                mods_doi = etree.SubElement(mods_xml, MODS + 'identifier')
                mods_doi.set('type', 'doi')
                mods_doi.text = self.publication.doi

            # Publisher
            publisher = self._get_publisher_name()

            if publisher is not None:
                mods_publisher = etree.SubElement(mods_origin_info, MODS + 'publisher')
                mods_publisher.text = publisher

            # relatedItem
            related_item = self._get_xml_metadata_relatedItem()
            if related_item is not None:
                mods_xml.insert(0, related_item)

        # Language
        if len(form.cleaned_data['abstract']) >= 256:
            language = langdetect.detect_langs(form.cleaned_data['abstract'])[0]
            if language.prob >= 0.5:
                mods_language = etree.SubElement(mods_xml, MODS + 'language')
                mods_language_term = etree.SubElement(mods_language, MODS + 'languageTerm')
                mods_language_term.set('type', 'code')
                mods_language_term.set('authority', 'rfc3066')
                mods_language_term.text = language.lang

        # DDC
        ddcs = form.cleaned_data.get('ddc', None)
        if ddcs is not None:
            for ddc in ddcs:
                mods_classification_ddc = etree.SubElement(mods_xml, MODS + 'classification')
                mods_classification_ddc.set('authority', 'ddc')
                mods_classification_ddc.text = ddc.number_as_string


        # Name / Authors list
        for author in self.paper.authors:
            mods_name = etree.SubElement(mods_xml, MODS + 'name')
            mods_name.set('type', 'personal')
            mods_last_name = etree.SubElement(mods_name, MODS + 'namePart')
            mods_last_name.set('type', 'family')
            mods_last_name.text = author.name.last
            mods_first_name = etree.SubElement(mods_name, MODS + 'namePart')
            mods_first_name.set('type', 'given')
            mods_first_name.text = author.name.first
            if author.orcid is not None:
                mods_orcid = etree.SubElement(mods_name, MODS + 'nameIdentifier')
                mods_orcid.set('type', 'orcid')
                mods_orcid.text = author.orcid

        # Title
        mods_title_info = etree.SubElement(mods_xml, MODS + 'titleInfo')
        mods_title = etree.SubElement(mods_title_info, MODS + 'title')
        mods_title.text = self.paper.title

        # Document type
        mods_type = etree.SubElement(mods_xml, MODS + 'genre')
        mods_type.text = self.paper.doctype

        return mods_xml

        
    def _get_xml_metadata_relatedItem(self):
        """
        Creates the mods item ``relatedItem`` if available
        :returns: lxml object or ``None``
        """
        related_item = None
        related_item_data = dict()

        # We set the title and publisher, but prefer values from Journal or Publisher object if available
        journal = self.publication.journal
        issn = None
        eissn = None
        if self.publication.journal is not None:
            journal = self.publication.journal.title
            issn = self.publication.journal.issn
            eissn = self.publication.journal.essn
        else:
            journal = self.publication.journal_title

        # Set the title
        if journal is not None:
            related_item_title_info = etree.Element(MODS + 'titleInfo')
            related_item_title = etree.SubElement(related_item_title_info, MODS + 'title')
            related_item_title.text = journal
            related_item_data['title'] = related_item_title_info

        # Set issn
        if issn is not None:
            related_item_issn = etree.Element(MODS + 'identifier')
            related_item_issn.set('type', 'issn')
            related_item_issn.text = issn
            related_item_data['issn'] = related_item_issn

        # Set issn
        if eissn is not None:
            related_item_eissn = etree.Element(MODS + 'identifier')
            related_item_eissn.set('type', 'eissn')
            related_item_eissn.text = eissn
            related_item_data['eissn'] = related_item_eissn

        # relatedItem - part
        part = dict()

        # Set pages
        if self.publication.pages is not None:
            pages = self.publication.pages.split('-', 1)
            related_item_pages = etree.Element(MODS + 'extent')
            related_item_pages.set('unit', 'pages')
            if len(pages) == 1:
                related_item_pages_total = etree.SubElement(related_item_pages, MODS + 'total')
                related_item_pages_total.text = self.publication.pages
                part['pages'] = related_item_pages
            else:
                start = pages[0]
                end = pages[1]
                related_item_pages_start = etree.SubElement(related_item_pages, MODS + 'start')
                related_item_pages_start.text = start
                related_item_pages_start = etree.SubElement(related_item_pages, MODS + 'end')
                related_item_pages_start.text = end
                part['pages'] = related_item_pages

        # Set issue
        if self.publication.issue is not None:
            related_item_issue = etree.Element(MODS + 'detail')
            related_item_issue.set('type', 'issue')
            related_item_issue_number = etree.SubElement(related_item_issue, MODS + 'number')
            related_item_issue_number.text = self.publication.issue
            part['issue'] = related_item_issue

        # Set volume
        if self.publication.volume is not None:
            related_item_volume = etree.Element(MODS + 'detail')
            related_item_volume.set('type', 'volume')
            related_item_volume_number = etree.SubElement(related_item_volume, MODS + 'number')
            related_item_volume_number.text = self.publication.volume
            part['volume'] = related_item_volume

        # Make parts if existing
        if len(part) >= 1:
            related_item_part = etree.Element(MODS + 'part')
            for item in part.values():
                related_item_part.insert(0, item)
            related_item_data['part'] = related_item_part

        # Make relatedItem if existing
        if len(related_item_data) >= 1:
            related_item = etree.Element(MODS + 'relatedItem')
            for item in related_item_data.values():
                related_item.insert(0, item)
        
        return related_item


protocol_registry.register(SWORDMETSMODSProtocol)
