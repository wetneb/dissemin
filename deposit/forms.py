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

from deposit.models import Repository
from deposit.models import UserPreferences
from django import forms
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext as __
from django.utils.translation import ugettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from papers.models import UPLOAD_TYPE_CHOICES
from upload.models import UploadedPDF


class PaperDepositForm(forms.Form):
    """
    Main form for the deposit.
    It references both the file (as an ID) and the upload type.
    """
    file_id = forms.IntegerField()
    radioUploadType = forms.ChoiceField(
        label=_('Upload type'), choices=UPLOAD_TYPE_CHOICES)
    radioRepository = forms.ModelChoiceField(label=_('Repository'),
                                             queryset=Repository.objects.all())

    def clean_file_id(self):
        file_id = self.cleaned_data['file_id']
        try:
            uploadedPDF = UploadedPDF.objects.get(pk=file_id)
        except UploadedPDF.NotFound:
            raise forms.ValidationError(
                __("Invalid full text identifier."), code='invalid_file_id')
        return uploadedPDF


def wrap_with_prefetch_status(baseWidget, get_callback, fieldname):
    """
    Add a status text above the widget to display the prefetching status
    of the data in the field.

    :param baseWidget: the :class:`Widget` to be prefetched: the prefetching
            status will be displayed above that widget and its value will
            be set by the JS code
    :param get_callback: function returning the AJAX URL where to get
        the prefetching status from. This is a callback and not a plain
        string for technical reasons (the URL cannot be computed before
        Django is fully loaded).
    :param fieldname: The name of the field to be prefetched, passed
        to the AJAX callback.
    """
    orig_render = baseWidget.render

    def new_render(self, name, value, attrs=None):
        base_html = orig_render(self, name, value, attrs)
        callback = get_callback()
        if value:
            return base_html
        return ('<span class="prefetchingFieldStatus" data-callback="%s" data-fieldid="%s" data-fieldname="%s" data-objfieldname="%s"></span>' % (callback, attrs['id'], name, fieldname))+base_html
    baseWidget.render = new_render
    return baseWidget


class BaseMetadataForm(forms.Form):
    """
    Base form for repository-specific options
    """
    def __init__(self, paper, **kwargs):
        super(BaseMetadataForm, self).__init__(**kwargs)
        # Subclasses can reimplement this and do things based on the
        # paper instance (for instance, initializing choices).
        # The paper_id field is not filled here, because that should
        # only happen when filling the form with initial data.

    # Dummy field to store the paper id (required for dynamic fetching of the
    # abstract)
    paper_id = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput
    )

class FormWithAbstract(BaseMetadataForm):
    """
    A simple metadata form, only including the abstract.
    Repositories can subclass this form to add more fields.
    """
    abstract = forms.CharField(
            label=__('Abstract'),
            required=True,
            widget=wrap_with_prefetch_status(forms.Textarea,
                                             lambda: reverse(
                                                 'ajax-waitForConsolidatedField'),
                                             'paper_id')(attrs={'class': 'form-control'})
            )


### Form for global preferences ###

class PreferredRepositoryField(forms.ModelChoiceField):
    def __init__(self, *args, **kwargs):
        kwargs['empty_label'] = _('No preferred repository')
        super(PreferredRepositoryField, self).__init__(*args, **kwargs)

class UserPreferencesForm(forms.ModelForm):
    class Meta:
        model = UserPreferences
        fields = ['email', 'preferred_repository']
        widgets = {
            'preferred_repository': forms.RadioSelect(attrs={'class':'radio-margin'}),
        }
        field_classes = {
            'preferred_repository': PreferredRepositoryField,
        }

    def __init__(self, *args, **kwargs):
        super(UserPreferencesForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        #self.helper.form_class = 'form-horizontal'
        #self.helper.label_class = 'col-lg-2'
        #self.helper.field_class = 'col-lg-8'
        self.helper.add_input(
            Submit('submit', __('Save')),
        )



