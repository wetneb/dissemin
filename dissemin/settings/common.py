# -*- encoding: utf-8 -*-

# Dissemin: open access policy enforcement tool
# Copyright (C) 2014 Antonin Delpeuch
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#


"""
Django settings for dissemin project.

See the doc for details of usage:
https://dev.dissem.in/install.html

For the full list of Django settings and their values, see
https://docs.djangoproject.com/en/1.8/ref/settings/
"""

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
from datetime import timedelta
import os

from django.utils.translation import ugettext_lazy as _

try:
    from .secret import PROAIXY_API_KEY
    from .secret import DATABASES
    from .secret import EMAIL_HOST
    from .secret import EMAIL_HOST_PASSWORD
    from .secret import EMAIL_HOST_USER
    from .secret import EMAIL_USE_TLS
    from .secret import REDIS_DB
    from .secret import REDIS_HOST
    from .secret import REDIS_PASSWORD
    from .secret import REDIS_PORT
    from .secret import ROMEO_API_KEY
    from .secret import SECRET_KEY
except ImportError as e:
    raise RuntimeError(
        'Secret file is missing, did you forget to add a secret.py in your settings folder?')

try:
    from .secret import RAVEN_CONFIG
except ImportError:
    pass  # Non-mandatory secrets.

# dirname(__file__) → repo/dissemin/settings/common.py
# .. → repo/dissemin/settings
# .. → repo/dissemin
# .. → repo/

BASE_DIR = os.path.dirname(os.path.join(
    os.path.dirname(__file__), '..', '..', '..'))


### DOI proxy ###
# The interface where to get DOI metadata from.
#
# This interface should at least support fetching metadata for one
# single DOI, like this:
# curl -LH "Accept: application/citeproc+json" http://DOI_PROXY_DOMAIN/10.1080/15568318.2012.660115
# (returns the citation as Citeproc+JSON)
#
# This acts as a caching proxy for doi.org
DOI_PROXY_DOMAIN = 'doi-cache.dissem.in'
#
# In addition, if the endpoint supports it, batch requests can be performed:
# curl -d 'dois=["10.1016/j.physletb.2015.01.010","10.5380/dp.v1i1.1922","10.1007/978-3-319-10936-7_9"]' \\
#        http://doi-cache.ulminfo.fr/batch
# (returns a list of citation in Citeproc+JSON format)
#
DOI_PROXY_SUPPORTS_BATCH = True
# Uncomment these settings if you rather want
# to fetch metadata directly from CrossRef (slower as not cached,
# and more requests as there is no batch support).
#DOI_PROXY_DOMAIN =  'doi.org'
#DOI_PROXY_SUPPORTS_BATCH = False

# Proaixy API key
# Used to fetch paper metadata. Get one by asking developers@dissem.in
# This is a default key that should only be used for tests
if PROAIXY_API_KEY is None:
    PROAIXY_API_KEY = '46f664aaae8d25826ff6'


### RoMEO proxy ###
# Set this to 'sherpa.ac.uk' if our custom mirror is not up anymore.
# Otherwise our proxy caches results and is more reliable than the
# original endpoint.
ROMEO_API_DOMAIN = 'romeo-cache.dissem.in'

### Paper deposits ###
# Max size of the PDFs (in bytes)
# 2.5MB - 2621440
# 5MB - 5242880
# 10MB - 10485760
# 20MB - 20971520
# 50MB - 5242880
DEPOSIT_MAX_FILE_SIZE = 1024*1024*20  # 20 MB
# Max download time when the file is downloaded from an URL (in seconds)
URL_DEPOSIT_DOWNLOAD_TIMEOUT = 10

### Paper freshness options ###
# On login of an user, minimum time between the last harvest to trigger
# a new harvest for that user.
PROFILE_REFRESH_ON_LOGIN = timedelta(days=1)

### Application definition ###
# You should not have to change anything in this section.

INSTALLED_APPS = (
    'dal',
    'dal_select2',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'bootstrap3_datepicker',
    'rest_framework',
    'crispy_forms',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.orcid',
    'statistics',
    'publishers',
    'papers',
    'upload',
    'deposit',
    'deposit.zenodo',
    'deposit.hal',
    'deposit.sword',
    'deposit.osf',
    'autocomplete',
    'notification',
    'bootstrap_pagination',
    'django_js_reverse',
    'solo',
    'haystack',
    'widget_tweaks',
    'capture_tag',
    'memoize',
    'django_countries',
    'leaflet',
    'djgeojson',
    'raven.contrib.django.raven_compat'
)

CRISPY_TEMPLATE_PACK = 'bootstrap3'

SITE_ID = 1

MIDDLEWARE_CLASSES = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
)

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
)


TEMPLATES = [
        {
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [
                os.path.join(BASE_DIR, 'templates')
            ],
            'OPTIONS': {
                'loaders': (
                    ('django.template.loaders.cached.Loader', (
                        'django.template.loaders.filesystem.Loader',
                        'django.template.loaders.app_directories.Loader',
                    )),
                ),
                'context_processors': (
                    "django.contrib.auth.context_processors.auth",
                    "django.template.context_processors.debug",
                    "django.template.context_processors.i18n",
                    "django.template.context_processors.media",
                    "django.template.context_processors.static",
                    "django.template.context_processors.tz",
                    "django.template.context_processors.request",
                    "dissemin.tcp.orcid_base_domain",
                ),
                'debug': True
            }
        }
]

ROOT_URLCONF = 'dissemin.urls'

WSGI_APPLICATION = 'dissemin.wsgi.application'


### Static files (CSS, JavaScript, Images) ###
# This defines how static files are stored and accessed.
# https://docs.djangoproject.com/en/1.8/howto/static-files/
#
# Relative URL where static files are accessed (you don't have to change this).
STATIC_URL = '/static/'
# Relative URL where user uploads are accessed (you don't have to change this).
MEDIA_URL = '/media/'

### Celery config ###
# Celery runs asynchronous tasks such as metadata harvesting or
# complex updates.
# To communicate with it, we need a "broker".
# This is an example broker with Redis
# (with settings configured in your secret.py)
REDIS_URL = ':%s@%s:%s/%d' % (
        REDIS_PASSWORD,
        REDIS_HOST,
        REDIS_PORT,
        REDIS_DB)
BROKER_URL = 'redis://'+REDIS_URL
# We also use Redis as result backend.
CELERY_RESULT_BACKEND = BROKER_URL

# Redis is not mandatory, this client is reserved for deposits.
try:
    import redis
    redis_client = redis.StrictRedis(
            host=REDIS_HOST, port=REDIS_PORT,
            db=REDIS_DB, password=REDIS_PASSWORD)
except ImportError:
    pass

CELERY_ACCEPT_CONTENT = ['pickle', 'json', 'msgpack', 'yaml']
CELERY_IMPORTS = ['backend.tasks']

CELERYBEAT_SCHEDULE = {
    'update_all_stats': {
        'task': 'update_all_stats',
        'schedule': timedelta(days=1),
    },
    'refresh_deposit_statuses': {
          'task': 'refresh_deposit_statuses',
          'schedule': timedelta(days=1),
    },
}

# This is the time in seconds before an unacknowledged task is re-sent to
# another worker. It should exceed the length of the longest task, otherwise
# it will be executed twice ! 43200 is one day.
BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 43200}

# Internationalization
# https://docs.djangoproject.com/en/1.8/topics/i18n/
LANGUAGE_CODE = 'en-us'
POSSIBLE_LANGUAGE_CODES = ['en', 'fr']
LANGUAGES = [
    ('en', _('English')),
    ('fr', _('French')),
    ('zh-hand', _('Simplified Chinese')),
    ('mk', _('Macedonian')),
]
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_L10N = True
USE_TZ = True
LOCALE_PATHS = (os.path.join(BASE_DIR, 'locale'),)

# Login and athentication
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'

# Settings for our own API
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
    'PAGE_SIZE': 10,
    'DEFAULT_PAGINATION_CLASS':
    'rest_framework.pagination.LimitOffsetPagination', # silences useless warning
    'DEFAULT_RENDERER_CLASSES': (
                'rest_framework.renderers.JSONRenderer',
                'rest_framework.renderers.BrowsableAPIRenderer',
            ),
}

# Custom backend for haystack with Elasticsearch
HAYSTACK_CONNECTIONS = {
    'default': {
        'ENGINE': 'search.SearchEngine',
        'URL': 'http://localhost:9200/',
        'INDEX_NAME': 'dissemin',
    },
}

# Deposit notification callback, can be overriden to notify an external
# service on deposit
DEPOSIT_NOTIFICATION_CALLBACK = (lambda payload: None)
