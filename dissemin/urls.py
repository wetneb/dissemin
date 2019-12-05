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


import allauth.account.views
from allauth.socialaccount import providers
from django.conf import settings
from django.urls import include
from django.urls import path
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.shortcuts import render
from django.views import generic
from django.views.i18n import JavaScriptCatalog
import django_js_reverse.views

from upload.views import FileDownloadView

admin.autodiscover()

try:
    import importlib
except ImportError:
    from django.utils import importlib


def handler404(request, exception=None):
    response = render(request, '404.html', {'exception':exception})
    response.status_code = 404
    return response


def handler500(request, exception=None):
    response = render(request, '500.html', {'exception':exception})
    response.status_code = 500
    return response


class LoginView(generic.TemplateView):
    template_name = 'dissemin/login.html'


class SandboxLoginView(allauth.account.views.LoginView):
    template_name = 'dissemin/sandbox.html'


def logoutView(request):
    logout(request)
    if 'HTTP_REFERER' in request.META:
        return redirect(request.META['HTTP_REFERER'])
    else:
        return redirect('/')


def temp(name):
    def handler(request, *args, **kwargs):
        return render(request, name, {})
    return handler

js_info_dict = {
    'packages': (
        'dissemin'
    )
}

urlpatterns = [
    path('file/<int:pk>/<str:token>/', FileDownloadView.as_view(), name='file-download'),
    # Errors
    path('404-error', temp('404.html')),
    path('500-error', temp('500.html')),
    # Static views
    path('sources', temp('dissemin/sources.html'), name='sources'),
    path('faq', temp('dissemin/faq.html'), name='faq'),
    path('tos', temp('dissemin/tos.html'), name='tos'),
    # Admin interface
    path('admin/', admin.site.urls),
    # Apps
    path('ajax-upload/', include('upload.urls')),
    path('', include('papers.urls')),
    path('', include('publishers.urls')),
    path('', include('deposit.urls')),
    path('', include('notification.urls')),
    path('', include('autocomplete.urls')),
    path('jsreverse/', django_js_reverse.views.urls_js, name='js_reverse'),
    # Social auth
    path('accounts/login/', LoginView.as_view(), name='account_login'),
    path('accounts/sandbox_login/',
        SandboxLoginView.as_view(), name='sandbox-login'),
    path('accounts/logout/', logoutView, name='account_logout'),
    path('accounts/social/', include('allauth.socialaccount.urls')),
    # JavaScript i18n
    path('jsi18n/', JavaScriptCatalog.as_view(), name='javascript-catalog'),
    path('lang/', include('django.conf.urls.i18n'), name='set_language'),
    # Remove this in production
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT
           ) + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Allauth social providers (normally included directly in the standard installation
# of django-allauth, but as we disabled normal auth, we have to do it here).
for provider in providers.registry.get_list():
    try:
        prov_mod = importlib.import_module(provider.get_package() + '.urls')
    except ImportError:
        continue
    prov_urlpatterns = getattr(prov_mod, 'urlpatterns', None)
    if prov_urlpatterns:
        urlpatterns += prov_urlpatterns

# Debug toolbar
if 'debug_toolbar' in settings.INSTALLED_APPS:
    import debug_toolbar
    urlpatterns.append(
      path('__debug__/', include(debug_toolbar.urls)))

