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



from time import sleep

import logging
import requests
import requests.exceptions
from datetime import datetime
from datetime import timedelta

from dissemin.settings import redis_client
from memoize import memoize


logger = logging.getLogger('dissemin.' + __name__)

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

def request_retry(url, **kwargs):
    """
    Retries a request, with throttling and exponential back-off.

    :param url: the URL to fetch
    :param data: the GET parameters
    :param headers: the HTTP headers
    :param timeout: the number of seconds to wait before declaring that an individual request timed out (default 10)
    :param retries: the number of times to retry a query (default 3)
    :param delay: the minimum delay between requests (default 5)
    :param backoff: the multiple used when raising the delay after an unsuccessful query (default 2)
    :param session: A session to use
    """
    params = kwargs.get('params', None)
    timeout = kwargs.get('timeout', 10)
    retries = kwargs.get('retries', 5)
    delay = kwargs.get('delay', 5)
    backoff = kwargs.get('backoff', 2)
    headers = kwargs.get('headers', {})
    session = kwargs.get('session', requests.Session())
    try:
        r = session.get(url,
                         params=params,
                         timeout=timeout,
                         headers=headers,
                         allow_redirects=True)
        r.raise_for_status()
        return r
    except requests.exceptions.RequestException:
        if retries <= 0:
            raise

    logger.info("Retrying in "+str(delay)+" seconds with url "+url)
    sleep(delay)
    return request_retry(url,
                         params=params,
                         timeout=timeout,
                         retries=retries-1,
                         delay=delay*backoff,
                         backoff=backoff,
                         session=session)

def urlopen_retry(url, **kwargs):
    return request_retry(url, **kwargs).text

@memoize(timeout=86400)  # 1 day
def cached_urlopen_retry(*args, **kwargs):
    return urlopen_retry(*args, **kwargs)


def utf8_truncate(s, length=1024):
    """
    Truncates a string to given length when converted to utf8.
    :param s: string to truncate
    :param length: Desired length, default 1024
    :returns: String of utf8-length with at most 1024

    We cannot convert to utf8 and slice, since this might yield incomplete characters when decoding back.
    """
    s = s[:1024]

    while len(s.encode('utf-8')) > length:
        s = s[:-1]

    return s


def with_speed_report(generator, name=None, report_delay=timedelta(seconds=10)):
    """
    Periodically reports the speed at which we are enumerating the items
    of a generator.

    :param name: a name to use in the reports (eg "papers from Crossref API")
    :param report_delay: print a report every so often
    """
    if name is None:
        name = getattr(generator, "__name__", "")
    last_report = datetime.now()
    nb_records_since_last_report = 0
    for idx, record in enumerate(generator):
        yield record
        nb_records_since_last_report += 1
        now = datetime.now()
        if last_report + report_delay < now:
            rate = nb_records_since_last_report / float((now - last_report).total_seconds())
            logger.info('{}: {}, {} records/sec'.format(name, idx, rate))
            last_report = now
            nb_records_since_last_report = 0

def report_speed(name=None, report_delay=timedelta(seconds=10)):
    """
    Decorator for a function that returns a generator, see with_speed_report
    """
    def decorator(func):
        logging_name = name
        if logging_name is None:
            logging_name = getattr(func, "__name__", "")
        def wrapped_generator(*args, **kwargs):
            return with_speed_report(func(*args, **kwargs), name=logging_name, report_delay=report_delay)
        return wrapped_generator
    return decorator


def group_by_batches(generator, batch_size=100):
    """
    Given a generator, returns a generator of groups of at most batch_size elements.
    """
    current_batch = []
    for item in generator:
        current_batch.append(item)
        if len(current_batch) == batch_size:
            yield current_batch
            current_batch = []
    if current_batch:
        yield current_batch
