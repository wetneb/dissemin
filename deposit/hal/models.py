# -*- encoding: utf-8 -*-

from __future__ import unicode_literals

from django.db import models
from django.utils.translation import ugettext_lazy as _
from deposit.models import DepositPreferences


class HALDepositPreferences(DepositPreferences):
    on_behalf_of = models.CharField(max_length=128,
                null=True,
                blank=True,
                verbose_name=_('HAL username'),
                help_text=_('If set, deposits will be associated to this HAL account.'))


