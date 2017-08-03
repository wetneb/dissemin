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

import datetime
import re
import unicodedata

from lxml.html.clean import Cleaner
from titlecase import titlecase
import unicode_tex
from unidecode import unidecode

### General string utilities ###

filter_punctuation_alphanum_regex = re.compile(r'.*\w')

year_margin = 3

def filter_punctuation(lst):
    """
    :param lst: list of strings
    :returns: all the strings that contain at least one alphanumeric character

    >>> filter_punctuation([u'abc',u'ab.',u'/,',u'a-b',u'#=', u'0'])
    [u'abc', u'ab.', u'a-b', u'0']
    """
    return [ c for c in lst if filter_punctuation_alphanum_regex.match(c) is not None ]


def nocomma(lst):
    """
    Join fields using ',' ensuring that it does not appear in the fields
    This is used to output similarity graphs to be visualized with Gephi.

    :param lst: list of strings
    :returns: these strings joined by commas, ensuring they do not contain
        commas themselves

    >>> nocomma([u'a',u'b',u'cd'])
    u'a,b,cd'
    >>> nocomma([u'a,',u'b'])
    u'a,b'
    >>> nocomma([u'abc',u'',u'\\n',u'def'])
    u'abc, , ,def'
    """
    lst = [str(x).replace(',', '').replace('\n', '') for x in lst]
    lst = [x or ' ' for x in lst]
    return ','.join(lst)


def ulower(s):
    """
    Converts to unicode and lowercase.
    :param s: a string
    :return: unicode(s).lower()

    >>> ulower('abSc')
    u'absc'
    >>> ulower(None)
    u'none'
    >>> ulower(89)
    u'89'
    """
    return unicode(s).lower()


def nstrip(s):
    """
    Just like unicode.strip(), but works for None too.

    >>> nstrip(None) is None
    True
    >>> nstrip(u'aa')
    u'aa'
    >>> nstrip(u'  aa \\n')
    u'aa'
    """
    return s.strip() if s else None


def remove_diacritics(s):
    """
    Removes diacritics using the `unidecode` package.

    :param: an str or unicode string
    :returns: if str: the same string. if unicode: the unidecoded string.

    >>> remove_diacritics(u'aéèï')
    'aeei'
    >>> remove_diacritics(u'aéè'.encode('utf-8'))
    'a\\xc3\\xa9\\xc3\\xa8'
    """
    if isinstance(s, unicode):
        # for issue #305
        # because I have no idea what the general solution for this would be
        s = s.replace("’", "'")

        return unidecode(s)
    else:
        return s


def iunaccent(s):
    """
    Removes diacritics and case.

    >>> iunaccent(u'BÉPO forever')
    'bepo forever'
    """
    return remove_diacritics(s).lower()


tokenize_space_re = re.compile(r'\s+')


def tokenize(l):
    """
    A (very very simple) tokenizer.

    >>> tokenize(u'Hello world!')
    [u'Hello', u'world!']
    >>> tokenize(u'99\\tbottles\\nof  beeron \\tThe Wall')
    [u'99', u'bottles', u'of', u'beeron', u'The', u'Wall']
    """
    return tokenize_space_re.split(l)


def maybe_recapitalize_title(title):
    """
    Recapitalize a title if it is mostly uppercase
    (number of uppercase letters > number of lowercase letters)

    >>> maybe_recapitalize_title(u'THIS IS CALLED SCREAMING')
    u'This Is Called Screaming'
    >>> maybe_recapitalize_title(u'This is just a normal title')
    u'This is just a normal title'
    >>> maybe_recapitalize_title(u'THIS IS JUST QUITE Awkward')
    u'THIS IS JUST QUITE Awkward'
    """
    nb_upper, nb_lower = 0, 0
    for letter in title:
        if letter.isupper():
            nb_upper += 1
        elif letter.islower():
            nb_lower += 1

    if nb_upper > nb_lower:
        return titlecase(title)
    else:
        return title

# HTML sanitizing for the title

overescaped_re = re.compile(r'&amp;#(\d+);')
unicode4_re = re.compile(r'(\\u[0-9A-Z]{4})(?![0-9A-Z])')
whitespace_re = re.compile(r'\s+')
ltgt_re = re.compile(r'.*[<>&]')

html_cleaner = Cleaner()
html_cleaner.allow_tags = ['sub', 'sup', 'b', 'span']
html_cleaner.remove_unknown_tags = False

html_killer = Cleaner()
html_killer.allow_tags = ['div']
html_killer.remove_unknown_tags = False

latexmath_re = re.compile(r'\$(\S[^$]*?\S|\S)\$')


def remove_latex_math_dollars(string):
    """
    Removes LaTeX dollar tags.

    >>> remove_latex_math_dollars(u'This is $\\\\beta$-reduction explained')
    u'This is \\\\beta-reduction explained'
    >>> remove_latex_math_dollars(u'Compare $\\\\frac{2}{3}$ to $\\\\pi$')
    u'Compare \\\\frac{2}{3} to \\\\pi'
    >>> remove_latex_math_dollars(u'Click here to win $100')
    u'Click here to win $100'
    >>> remove_latex_math_dollars(u'What do you prefer, $50 or $100?')
    u'What do you prefer, $50 or $100?'
    """
    return latexmath_re.sub(r'\1', string)

latex_command_re = re.compile(
    r'(?P<command>\\([a-zA-Z]+|[.=\'\`"])({[^}]*})*)(?P<letter>[a-zA-Z])?')


def unescape_latex(s):
    """
    Replaces LaTeX symbols by their unicode counterparts using
    the `unicode_tex` package.

    >>> unescape_latex(u'the $\\\\alpha$-rays of $\\\\Sigma$-algebras')
    u'the $\\u03b1$-rays of $\\u03a3$-algebras'
    >>> unescape_latex(u'$\\textit{K}$ -trivial')
    u'$\\textit{K}$ -trivial'
    """
    def conditional_replace(fragment):
        cmd = fragment.group('command')
        letter = fragment.group('letter') or ''

        rep = unicode_tex.tex_to_unicode_map.get(cmd) or cmd

        # We inverse the order to handle accents.
        if cmd == r"\'" or cmd == r"\`":
            # We normalize back to the normal form to get only one unicode
            # character.
            return unicodedata.normalize('NFC', letter + rep)
        else:
            # Let's just concat.
            return rep + letter

    return latex_command_re.sub(conditional_replace, s)

latex_one_character_braces_re = re.compile(
    r'(^|(^|[^\\])\b(\w+)){(.)}', re.UNICODE)
latex_full_line_braces_re = re.compile(r'^{(.*)}$')
latex_word_braces_re = re.compile(r'(^|\s){(\w+)}($|\s)', re.UNICODE)


def remove_latex_braces(s):
    """
    Removes spurious braces such as in "Th{é}odore" or "a {CADE} conference"
    This should be run *after* unescape_latex

    >>> remove_latex_braces(u'Th{é}odore')
    u'Th\\xe9odore'
    >>> remove_latex_braces(u'the {CADE} conference')
    u'the CADE conference'
    >>> remove_latex_braces(u'consider 2^{a+b}')
    u'consider 2^{a+b}'
    >>> remove_latex_braces(u'{why these braces?}')
    u'why these braces?'
    """
    s = latex_full_line_braces_re.sub(r'\1', s)
    s = latex_word_braces_re.sub(r'\1\2\3', s)
    s = latex_one_character_braces_re.sub(r'\1\4', s)
    s = latex_one_character_braces_re.sub(r'\1\4', s)
    s = latex_one_character_braces_re.sub(r'\1\4', s)
    return s


def sanitize_html(s):
    """
    Removes most HTML tags, keeping the harmless ones.
    This also renders some LaTeX characters with `unescape_latex`,
    fixes overescaped HTML characters, and a few other fixes.

    >>> sanitize_html('My title<sub>is</sub><a href="http://dissem.in"><sup>nice</sup></a>')
    u'My title<sub>is</sub><sup>nice</sup>'
    >>> sanitize_html('$\\\\alpha$-conversion')
    u'$\\u03b1$-conversion'
    >>> sanitize_html('$$\\\\eta + \\\\omega$$')
    u'$\\u03b7 + \\u03c9$'
    >>> sanitize_html('abc & def')
    u'abc &amp; def'
    """
    s = overescaped_re.sub(r'&#\1;', s)
    s = unicode4_re.sub(lambda x: x.group(1).decode('unicode-escape'), s)
    s = whitespace_re.sub(r' ', s)
    s = unescape_latex(s)
    s = kill_double_dollars(s)
    if ltgt_re.match(s): # only run HTML sanitizer if there is a
                         # '<', '>' or '&'
        orig = html_cleaner.clean_html('<span>'+s+'</span>')
        s = orig[6:-7] # We cut the <span />
    return s


def kill_html(s):
    """
    Removes every tag except <div> (but there are no
    <div> in titles as sanitize_html removes them)

    >>> kill_html('My title<sub>is</sub><a href="http://dissem.in"><sup>nice</sup>    </a>')
    u'My titleisnice'
    """
    if ltgt_re.match(s): # only run HTML sanitizer if there is a '<' or '>'
        orig = html_killer.clean_html('<div>'+s+'</div>')
        return orig[5:-6].strip()  # We cut the <div />
    else:
        return s

latex_double_dollar_re = re.compile(r'\$\$([^\$]*?)\$\$')


def kill_double_dollars(s):
    """
    Removes double dollars (they generate line breaks with MathJax)
    This is included in the sanitize_html function.

    >>> kill_double_dollars('This equation $$\\\\mathrm{P} = \\\\mathrm{NP}$$ breaks my design')
    u'This equation $\\\\mathrm{P} = \\\\mathrm{NP}$ breaks my design'
    """
    s = latex_double_dollar_re.sub(r'$\1$', s)
    return s


def urlize(val):
    """
    Ensures a would-be URL actually starts with "http://" or "https://".

    :param val: the URL
    :returns: the cleaned URL

    >>> urlize(u'gnu.org')
    u'http://gnu.org'
    >>> urlize(None) is None
    True
    >>> urlize(u'https://gnu.org')
    u'https://gnu.org'
    """
    if val and not val.startswith('http://') and not val.startswith('https://'):
        val = 'http://'+val
    return val

domain_re = re.compile(r'\s*(https?|ftp)://(([a-zA-Z0-9-_]+\.)+[a-zA-Z]+)/?')

def extract_domain(url):
    """
    Extracts the domain name of an url

    >>> extract_domain(u'https://gnu.org/test.html')
    u'gnu.org'
    >>> extract_domain(u'nonsense') is None
    True
    """
    match = domain_re.match(url)
    if match:
        return match.group(2)



# JSON utilities !


def jpath(path, js, default=None):
    """
    XPath for JSON!

    :param path: a list of keys to follow in the tree of dicts, written in a string,
                separated by forward slashes
    :param default: the default value to return when the key is not found

    >>> jpath(u'message/items', {u'message':{u'items':u'hello'}})
    u'hello'
    """
    def _walk(lst, js):
        if js is None:
            return default
        if lst == []:
            return js
        else:
            return _walk(lst[1:], js.get(lst[0], {} if len(lst) > 1 else default))
    r = _walk(path.split('/'), js)
    return r


def remove_nones(dct):
    """
    Return a dict, without the None values

    >>> remove_nones({u'orcid':None,u'wtf':u'pl'})
    {u'wtf': u'pl'}
    >>> remove_nones({u'orcid':u'blah',u'hey':u'you'})
    {u'orcid': u'blah', u'hey': u'you'}
    >>> remove_nones({None:1})
    {None: 1}
    """
    return dict((k,v) for k,v in  dct.items() if v is not None)

# Partial date representation


def try_date(year, month, day):
    try:
        return datetime.date(year=year, month=month, day=day)
    except ValueError:
        return None


def parse_int(val, default):
    """
    Returns an int or a default value if parsing the int failed.

    >>> parse_int(90, None)
    90
    >>> parse_int(None, 90)
    90
    >>> parse_int('est', 8)
    8
    """
    try:
        return int(val)
    except ValueError:
        return default
    except TypeError:
        return default


def date_from_dateparts(dateparts):
    """
    Constructs a date from a list of at most 3 integers.

    >>> date_from_dateparts([])
    datetime.date(1970, 1, 1)
    >>> date_from_dateparts([2015])
    datetime.date(2015, 1, 1)
    >>> date_from_dateparts([2015,02])
    datetime.date(2015, 2, 1)
    >>> date_from_dateparts([2015,02,16])
    datetime.date(2015, 2, 16)
    >>> date_from_dateparts([2015,02,16])
    datetime.date(2015, 2, 16)
    >>> date_from_dateparts([2015,02,35])
    Traceback (most recent call last):
        ...
    ValueError: day is out of range for month
    """
    year = 1970 if len(dateparts) < 1 else parse_int(dateparts[0], 1970)
    month = 01 if len(dateparts) < 2 else parse_int(dateparts[1], 01)
    day = 01 if len(dateparts) < 3 else parse_int(dateparts[2], 01)
    return datetime.date(year=year, month=month, day=day)


def tolerant_datestamp_to_datetime(datestamp):
    """A datestamp to datetime that's more tolerant of diverse inputs.
    Taken from pyoai.

    >>> tolerant_datestamp_to_datetime('2016-02-11T18:34:12Z')
    datetime.datetime(2016, 2, 11, 18, 34, 12)
    >>> tolerant_datestamp_to_datetime('2016-02-11')
    datetime.datetime(2016, 2, 11, 0, 0)
    >>> tolerant_datestamp_to_datetime('2016/02/11')
    datetime.datetime(2016, 2, 11, 0, 0)
    >>> tolerant_datestamp_to_datetime('2016-02')
    datetime.datetime(2016, 2, 1, 0, 0)
    >>> tolerant_datestamp_to_datetime('2016')
    datetime.datetime(2016, 1, 1, 0, 0)
    >>> tolerant_datestamp_to_datetime('2016-02-11T18:34:12') # Z needed
    Traceback (most recent call last):
        ...
    ValueError: Invalid datestamp: 2016-02-11T18:34:12
    >>> tolerant_datestamp_to_datetime('2016-02-11-3') # too many numbers
    Traceback (most recent call last):
        ...
    ValueError: Invalid datestamp: 2016-02-11-3
    >>> tolerant_datestamp_to_datetime('2016-02-11T18:37:09:38') # too many numbers
    Traceback (most recent call last):
        ...
    ValueError: Invalid datestamp: 2016-02-11T18:37:09:38
    >>> tolerant_datestamp_to_datetime('20151023371')
    Traceback (most recent call last):
        ...
    ValueError: Invalid datestamp: 20151023371
    >>> tolerant_datestamp_to_datetime('2014T')
    Traceback (most recent call last):
        ...
    ValueError: Invalid datestamp: 2014T
    """
    splitted = datestamp.split('T')
    if len(splitted) == 2:
        d, t = splitted
        # if no Z is present, raise error
        if not t.endswith('Z'):
            raise ValueError("Invalid datestamp: "+str(datestamp))
        # split off Z at the end
        t = t[:-1]
    else:
        d = splitted[0]
        t = '00:00:00'
    if '/' in d and '-' not in d:
        d = d.replace('/', '-')
    d_splitted = d.split('-')
    if len(d_splitted) == 3:
        YYYY, MM, DD = d_splitted
    elif len(d_splitted) == 2:
        YYYY, MM = d_splitted
        DD = '01'
    elif len(d_splitted) == 1:
        YYYY = d_splitted[0]
        MM = '01'
        DD = '01'
    else:
        raise ValueError("Invalid datestamp: "+str(datestamp))
    if (len(YYYY) != 4 or
            len(MM) > 2 or
            len(DD) > 2):
        raise ValueError("Invalid datestamp: "+str(datestamp))

    t_splitted = t.split(':')
    if len(t_splitted) == 3:
        hh, mm, ss = t_splitted
    else:
        raise ValueError("Invalid datestamp: "+str(datestamp))
    return datetime.datetime(
        int(YYYY), int(MM), int(DD), int(hh), int(mm), int(ss))


def datetime_to_date(dt):
    """
    Converts a datetime or date object to a date object.

    >>> datetime_to_date(datetime.datetime(2016, 2, 11, 18, 34, 12))
    datetime.date(2016, 2, 11)
    >>> datetime_to_date(datetime.date(2015, 3, 1))
    datetime.date(2015, 3, 1)
    """
    if isinstance(dt, datetime.datetime):
        return dt.date()
    elif isinstance(dt, datetime.date):
        return dt
    raise ValueError("Invalid date or datetime")


def valid_publication_date(dt):
    """
    Checks that the date is not too far in the future
    (otherwise it is not a plausible publication date).

    >>> valid_publication_date(datetime.date(6789, 1, 1))
    False
    >>> valid_publication_date(datetime.date(2018, 3, 4))
    True
    >>> valid_publication_date(None)
    False
    """
    now = datetime.datetime.now()
    current_year = now.year
    # some papers are published in the future ("to appear")
    return ((isinstance(dt, datetime.date) or isinstance(dt, datetime.datetime))
            and dt.year < current_year + year_margin)

### ORCiD utilities ###

orcid_re = re.compile(
    r'^(https?://(sandbox.)?orcid.org/)?([0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[X0-9])$')


def validate_orcid(orcid):
    """
    :returns: a cleaned ORCiD if the argument represents a valid ORCiD, None otherwise

    This does not check that the id actually exists on orcid.org,
    only checks that it is syntactically valid (including the checksum).
    See http://support.orcid.org/knowledgebase/articles/116780-structure-of-the-orcid-identifier

    See the test suite for a more complete set of examples

    >>> validate_orcid(u' 0000-0001-8633-6098\\n')
    u'0000-0001-8633-6098'
    """
    if not orcid:
        return
    try:
        orcid = unicode(orcid).strip()
    except (ValueError, TypeError):
        return

    match = orcid_re.match(orcid)
    if not match:
        return
    orcid = match.group(3)
    nums = orcid.replace('-', '')
    total = 0
    for i in range(15):
        total = (total + int(nums[i])) * 2
    checkdigit = (12 - (total % 11)) % 11
    checkchar = str(checkdigit) if checkdigit != 10 else 'X'
    if nums[-1] == checkchar:
        return orcid


def affiliation_is_greater(a, b):
    """
    Compares to affiliation values. Returns True
    when the first contains more information than
    the second

    >>> affiliation_is_greater(None, None)
    False
    >>> affiliation_is_greater(None, 'UPenn')
    False
    >>> affiliation_is_greater('UPenn', None)
    True
    >>> affiliation_is_greater('0000-0001-8633-6098', 'Ecole normale superieure, Paris')
    True
    >>> affiliation_is_greater('Ecole normale superieure', 'Upenn')
    True
    """
    if a is None:
        return False
    if b is None:
        return True
    oa, ob = validate_orcid(a), validate_orcid(b)
    if oa and not ob:
        return True
    if ob and not oa:
        return False
    return len(a) > len(b)


# List utilities

def index_of(elem, choices):
    """
    Returns the index of elem (understood as a code) in the list of choices,
    where choices are expected to be pairs of (code,verbose_description).

    >>> index_of(42, [])
    0
    >>> index_of('ok', [('ok','This is ok'),('nok','This is definitely not OK')])
    0
    >>> index_of('nok', [('ok','This is ok'),('nok','This is definitely not OK')])
    1
    """
    for idx, (code, lbl) in enumerate(choices):
        if code == elem:
            return idx
    else:
        return 0
