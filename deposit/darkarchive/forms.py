from django import forms

from django.utils.translation import ugettext_lazy as _

from deposit.forms import BaseMetadataForm

class DarkArchiveForm(BaseMetadataForm):
    """
    Form that extends BaseMetadataForm for extra fields needed by DarkArchive protocol
    """

    field_order = ['email', 'abstract', 'license']

    email = forms.EmailField(
        label=_('E-mail'),
        required=True,
        max_length=255,
    )
