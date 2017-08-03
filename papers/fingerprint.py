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

import re

from papers.name import split_name_words
from papers.utils import kill_html
from papers.utils import remove_diacritics
from papers.utils import ulower

# Paper fingerprinting

stripped_chars = re.compile(r'[^- a-z0-9]')


def create_paper_plain_fingerprint(title, authors, year):
    """
    Creates a robust summary of a bibliographic reference.
    This plain fingerprint should then be converted to an
    actual fingerprint by hashing it (so that the length remains
    constant).

    :param title: the title of the paper
    :param authors: the list of author names, represented
        as (first_name, last_name) pairs
    :param year: the year of publication of the paper

    >>> create_paper_plain_fingerprint(' It  cleans whitespace And Case\\n',[('John','Doe')], 2015)
    u'it-cleans-whitespace-and-case/doe'
    >>> create_paper_plain_fingerprint('HTML tags are <emph>removed</emph>',[('John','Doe')], 2015)
    u'html-tags-are-removed/doe'
    >>> create_paper_plain_fingerprint('Les accents sont supprimés', [('John','Doe')],2015)
    u'les-accents-sont-supprimes/doe'
    >>> create_paper_plain_fingerprint('Long titles are unambiguous enough to be unique by themselves, no need for authors', [('John','Doe')], 2015)
    u'long-titles-are-unambiguous-enough-to-be-unique-by-themselves-no-need-for-authors'
    >>> create_paper_plain_fingerprint('Ambiguity', [('John','Doe')], 2014)
    u'ambiguity-2014/doe'
    """
    title = kill_html(title)
    title = remove_diacritics(title).lower()
    title = stripped_chars.sub('', title)
    title = title.strip()
    title = re.sub('[ -]+', '-', title)
    buf = title

    # If the title is long enough, we return the fingerprint as is
    if len(buf) > 50:
        return buf

    # If the title is very short, we add the year (for "Preface", "Introduction", "New members" cases)
    # if len(title) <= 16:
    if not '-' in title:
        buf += '-'+str(year)

    author_names_list = []
    for author in authors:
        if not author:
            continue
        author = (remove_diacritics(author[0]), remove_diacritics(author[1]))

        # Last name, without the small words such as "van", "der", "de"…
        last_name_words, last_name_separators = split_name_words(author[1])
        last_words = []
        for i, w in enumerate(last_name_words):
            if (w[0].isupper() or
                    (i > 0 and last_name_separators[i-1] == '-')):
                last_words.append(w)

        # If no word was uppercased, fall back on all the words
        if not last_words:
            last_words = last_name_words

        # Lowercase
        last_words = map(ulower, last_words)
        fp = '-'.join(last_words)
        author_names_list.append(fp)

    author_names_list.sort()
    for fp in author_names_list:
        buf += '/'+fp

    return buf
