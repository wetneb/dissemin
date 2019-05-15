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
Django settings for Dissemin project.

See the doc for details of usage:
https://dev.dissem.in/install.html

For the full list of Django settings and their values, see
https://docs.djangoproject.com/en/1.8/ref/settings/
"""

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
from datetime import timedelta
from dealer.git import git
import os

from django.utils.translation import ugettext_lazy as _

try:
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
    from .secret import SENTRY_DSN
except ImportError:
    raise RuntimeError(
        'A secret variable is missing, did you forget to add/update secret.py in your settings folder?')

if SENTRY_DSN:
    try:
        import sentry_sdk
    except ImportError:
        print('Sentry module is not available although a Sentry DSN was set. '
              'Disabling Sentry reporting...')
    else:
        sentry_sdk.init(dsn=SENTRY_DSN, release=git.revision)

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

### CrossRef politeness options ###
# These options determine how we identify ourselves to CrossRef.
# It is not mandatory to provide them but it helps get a better service.
CROSSREF_MAILTO = 'dev@dissem.in'
CROSSREF_USER_AGENT = 'Dissemin/0.1 (https://dissem.in/; mailto:dev@dissem.in)'

### Paper deposits ###
# Max size of the PDFs (in bytes)
# 2.5MB - 2621440
# 5MB - 5242880
# 10MB - 10485760
# 20MB - 20971520
# 50MB - 5242880
DEPOSIT_MAX_FILE_SIZE = 1024*1024*200  # 20 MB
# Max download time when the file is downloaded from an URL (in seconds)
URL_DEPOSIT_DOWNLOAD_TIMEOUT = 10

### Paper freshness options ###
# On login of an user, minimum time between the last harvest to trigger
# a new harvest for that user.
PROFILE_REFRESH_ON_LOGIN = timedelta(days=1)

### Application definition ###
# You should not have to change anything in this section.

INSTALLED_APPS = (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.humanize',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'rest_framework',
    'crispy_forms',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.orcid',
    'statistics',
    'publishers',
    'backend',
    'papers',
    'upload',
    'deposit',
    'deposit.zenodo',
    'deposit.hal',
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
    'bootstrap_datepicker_plus',
    'django_select2',
)

CRISPY_TEMPLATE_PACK = 'bootstrap3'

SELECT2_JS = None
SELECT2_CSS = None
SELECT2_I18N_PATH = 'libs/select2/i18n'

SITE_ID = 1

MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

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
                    'django.contrib.messages.context_processors.messages',
                    "django.template.context_processors.debug",
                    "django.template.context_processors.i18n",
                    "django.template.context_processors.media",
                    "django.template.context_processors.static",
                    "django.template.context_processors.tz",
                    "django.template.context_processors.request",
                    "django_settings_export.settings_export",
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
    'fetch_updates_from_romeo': {
           'task': 'fetch_updates_from_romeo',
           'schedule': timedelta(days=14),
    }
#    'update_crossref': {
#          'task': 'update_crossref',
#          'schedule': timedelta(days=1),
#    },
}

# This is the time in seconds before an unacknowledged task is re-sent to
# another worker. It should exceed the length of the longest task, otherwise
# it will be executed twice ! 43200 is one day.
BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 43200}

# Internationalization
# https://docs.djangoproject.com/en/1.8/topics/i18n/
LANGUAGE_CODE = 'en-us'
POSSIBLE_LANGUAGE_CODES = ['ar', 'bt-br', 'nl', 'en', 'fi', 'pt', 'fr', 'de', 'hi', 'ko', 'mk', 'pms', 'es', 'zh-hans', 'zh-hant', 'sv']
LANGUAGES = [
    ('ar', _('Arabic')),
    ('en', _('English')),
    ('fi', _('Finnish')),
    ('fr', _('French')),
    ('ko', _('Korean')),
    ('es', _('Spanish')),
    ('zh-hans', _('Simplified Chinese')),
    ('zh-hant', _('Traditional Chinese')),
    ('mk', _('Macedonian')),
    ('de', _('German')),
    ('pt-br', _('Brazilian Portuguese')),
    ('pt', _('European Portuguese')),
    ('sv', _('Swedish')),
]

EXTRA_LANG_INFO = {
    'pms': {
        'bidi': False,
        'code': 'pms',
        'fallback': ['it'],
        'name': 'Piedmontese',
        'name_local': 'Lenga piemontèisa',
    },
}

# Add custom languages not provided by Django
import django.conf.locale
LANG_INFO = dict(django.conf.locale.LANG_INFO, **EXTRA_LANG_INFO)
django.conf.locale.LANG_INFO = LANG_INFO


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

# URL to a self-hosted version of Mathjax
MATHJAX_SELFHOST_URL = None

# Should we display a ribbon indicating that we are not in production?
DISPLAY_BETA_RIBBON = True

# Settings to make available in the templates
# See https://github.com/jakubroztocil/django-settings-export#usage
SETTINGS_EXPORT = [
    'MATHJAX_SELFHOST_URL',
    'DISPLAY_BETA_RIBBON',
    'SENTRY_DSN',
]

# Logging is very important thing. Here we define some standards. We use Django logging system, so there it is easy to custimze your logging preferences.
# To switch for 'console' to level 'DEBUG' please use prod.py resp. dev.py
# To get a logger use logger = logging.getLogger('dissemin.' + __name__) to make sure that it is catched by the Dissemin logger.

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {
            'format': '%(asctime)s %(levelname)s %(name)s:%(lineno)s  %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'console',
        },
    },
    'loggers': {
    # root logger, includes also third party packages. To omit them them, put in 'django' to get just django related logging
        '': {
            'level': 'WARNING',
            'handlers': ['console'],
        },
    # Dissemin logger
        'dissemin' : {
            'level': None, # Change this value in prod.py resp dev.py
            'handlers': ['console'],
            'propagate': False,
        },
    },
}

# If sentry is set, we send all important logs to sentry.

if SENTRY_DSN:
    LOGGING['handlers'].update({
        'sentry': {
            'level': 'ERROR',
            'class': 'sentry_sdk.integrations.logging.EventHandler',
            }
        })

    LOGGING['loggers']['']['handlers'] += ['sentry']
    LOGGING['loggers']['dissemin']['handlers'] += ['sentry']
