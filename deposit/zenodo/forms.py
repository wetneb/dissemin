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

from deposit.forms import FormWithAbstract
from django import forms
from django.utils.translation import ugettext as _

ZENODO_LICENSES_CHOICES = [
   ('cc-zero',
    _('Creative Commons CCZero (CC0)')),
   ('cc-by',
    _('Creative Commons Attribution (CC-BY)')),
   ('cc-by-sa',
    _('Creative Commons Attribution-ShareAlike (CC-BY-SA)')),
   ('cc-by-nc-4.0',
    _('Creative Commons Attribution-NonCommercial (CC-BY-NC)')),
   ('cc-by-nd-4.0',
    _('Creative Commons Attribution-NoDerivatives (CC-BY-ND)')),
   ('zenodo-freetoread-1.0',
    _('Free for private use; right holder retains other rights, including distribution')),
   ('other-open',
    _('Other open license')),
 ]


class ZenodoForm(FormWithAbstract):
    license = forms.ChoiceField(
            label=_('License'),
            choices=ZENODO_LICENSES_CHOICES,
            initial='zenodo-freetoread-1.0',
            widget=forms.RadioSelect(attrs={'class': 'radio-margin'})
            )
