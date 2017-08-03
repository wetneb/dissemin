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

from __future__ import unicode_literals

from time import sleep

import requests
import requests.exceptions

from dissemin.settings import redis_client
from memoize import memoize
from papers.errors import MetadataSourceException


# Run a task at most one at a time


class run_only_once(object):

    def __init__(self, base_id, **kwargs):
        self.base_id = base_id
        self.keys = kwargs.get('keys', [])
        self.timeout = int(kwargs.get('timeout', 60*10))

    def __call__(self, f):
        def inner(*args, **kwargs):
            lock_id = self.base_id+'-' + \
                ('-'.join([str(kwargs.get(key, 'none')) for key in self.keys]))
            lock = redis_client.lock(lock_id, timeout=self.timeout)
            have_lock = False
            result = None
            try:
                have_lock = lock.acquire(blocking=False)
                if have_lock:
                    result = f(*args, **kwargs)
            finally:
                if have_lock:
                    lock.release()
            return result
        return inner


# Open an URL with retries

def urlopen_retry(url, **kwargs):  # data, timeout, retries, delay, backoff):
    data = kwargs.get('data', None)
    timeout = kwargs.get('timeout', 10)
    retries = kwargs.get('retries', 3)
    delay = kwargs.get('delay', 5)
    backoff = kwargs.get('backoff', 2)
    headers = kwargs.get('headers', {})
    try:
        r = requests.get(url,
                         params=data,
                         timeout=timeout,
                         headers=headers,
                         allow_redirects=True)
        return r.text
    except requests.exceptions.Timeout as e:
        if retries <= 0:
            raise MetadataSourceException('Timeout: '+str(e))
    except requests.exceptions.ConnectionError as e:
        if retries <= 0:
            raise MetadataSourceException('Connection error: '+str(e))
    except requests.exceptions.RequestException as e:
        raise MetadataSourceException('Request error: '+str(e))

    print "Retrying in "+str(delay)+" seconds..."
    print "URL: "+url
    sleep(delay)
    return urlopen_retry(url,
                         data=data,
                         timeout=timeout,
                         retries=retries-1,
                         delay=delay*backoff,
                         backoff=backoff)


@memoize(timeout=86400)  # 1 day
def cached_urlopen_retry(*args, **kwargs):
    return urlopen_retry(*args, **kwargs)
