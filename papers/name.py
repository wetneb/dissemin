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

import name_tools
from papers.utils import iunaccent
from papers.utils import remove_diacritics

# Name managemement: heuristics to separate a name into (first,last)
comma_re = re.compile(r',+')
space_re = re.compile(r'\s+')
initial_re = re.compile(r'(^|\W)\w(\W|$)', re.UNICODE)
lowercase_re = re.compile(r'[a-z]')  # TODO make this unicode-portable
# See
# http://stackoverflow.com/questions/5224835/what-is-the-proper-regular-expression-to-match-all-utf-8-unicode-lowercase-lette
letter_re = re.compile(r'\w', re.UNICODE)


def match_names(a, b):
    """
    Returns a boolean: are these two names compatible?
    Examples:
    > ('Robin', 'Ryder'),('R.', 'Ryder'): True
    > ('Robin J.', 'Ryder'),('R.', 'Ryder'): True
    > ('R. J.', 'Ryder'),('J.', 'Ryder'): True
    > ('R. K.', 'Ryder'),('K.', 'Ryder'): False
    > ('Claire', 'Mathieu'),('Claire', 'Kenyon-Mathieu'): False
    """
    return name_similarity(a, b) > 0.

initial_re = re.compile(r'[A-Z](\.,;)*$')
final_comma_re = re.compile(r',+( |$)')


def remove_final_comma(w):
    """
    Remove all commas following words
    """
    return final_comma_re.sub(r'\1', w)


def normalize_name_words(w):
    """
    If it is an initial, ensure it is of the form "T.", and recapitalize fully capitalized words.
    Also convert things like "Jp." to "J.-P."
    This function is to be called on first or last names only.
    """
    name_words, separators = split_name_words(w)
    all_lower = all(w.lower() == w for w in name_words)
    new_name_words = []
    for idx, word in enumerate(name_words):
        force = all_lower or (idx > 0 and separators[idx-1])
        new_name_words.append(recapitalize_word(word, force))
    name_words = map(remove_final_comma, new_name_words)
    return rebuild_name(name_words, separators)


def rebuild_name(name_words, separators):
    """ Reconstructs a name string out of words and separators, as returned by split_name_words.
    len(name_words) = len(separators) + 1 is assumed.

    :param name_words: The list of name words (without periods)
    :param separators: The list of separators ('' or '-').
    """
    separators = [' ' if s == '' else s for s in separators]
    output = ''
    for idx, word in enumerate(name_words):
        output += word
        if len(word) == 1:
            output += '.'
        if idx < len(separators):
            output += separators[idx]
        elif idx < len(name_words)-1:
            print("WARNING: incorrect name splitting for '%s'" %
                  unicode(name_words))
            output += ' '
    return output

common_abbr = set(['st', 'dr', 'prof', 'jr', 'sr',
                   'mr', 'ms', 'mrs', 'mme', 'fr'])
name_separator_re = re.compile(r'\w\b((\.*) *(-*) *)(\w|$)', re.UNICODE)


def split_name_words(string):
    """
    :returns: A pair of lists. The first one is the list of words, the second is the
              list of separators (either '' or '-')
    """
    buf = string.strip()
    words = []
    separators = []
    match = name_separator_re.search(buf)
    while match is not None:
        pos = match.start(1)
        if pos > 0 and pos < len(string):
            word = buf[:pos]
            buf = buf[match.end(1):]
            has_period = len(match.group(2)) > 0
            if has_period:
                if word.lower() in common_abbr:
                    words.append(word+'.')
                elif len(word) <= 3:
                    # A case like "Jp." or "Jpf."
                    # In this case we understand each letter as an initial
                    for idx, char in enumerate(word):
                        words.append(char.upper())
                        if idx < len(word)-1:
                            separators.append('-')
                else:
                    # A case like "Joseph."
                    # The period is probably here by mistake
                    # We want to avoid translating it to "J. O. S. E. P. H."
                    words.append(word)
            else:
                words.append(word)
            if len(match.group(4)):
                separators.append(match.group(3))
        else:
            break
        match = name_separator_re.search(buf)
    if buf:
        words.append(buf)
    return (words, separators)


def has_only_initials(string):
    words, separators = split_name_words(string)
    return all(len(w) == 1 for w in words)


def shorten_first_name(string):
    words, separators = split_name_words(string)
    result = ""
    for i, w in enumerate(words):
        if w[0].isupper():
            result += w[0]+'.'
            if i < len(separators):
                result += separators[i] if separators[i] else ' '
    return result


def recapitalize_word(w, force=False):
    """
    Turns every fully capitalized word into an uncapitalized word (except for the first character).
    By default, only do it if the word is fully capitalized.
    """
    if (w.upper() == w and len(w) > 1) or force:
        previousIsChar = False
        res = ''
        for i in range(len(w)):
            if previousIsChar:
                res += w[i].lower()
            elif i == 0:
                res += w[i].upper()
            else:
                res += w[i]
            previousIsChar = letter_re.match(w[i]) != None
        return res
    return w


def match_first_names(pair):
    """
    Returns true when the given pair of first names
    is compatible.

    >>> match_first_names(('A','Amanda'))
    True
    >>> match_first_names(('Amanda','Amanda'))
    True
    >>> match_first_names(('Alfred','Amanda'))
    False
    >>> match_first_names(('patrick','P'))
    True
    >>> match_first_names((None,'Iryna'))
    True
    >>> match_first_names(('Clément','Clement'))
    True
    """
    a, b = pair
    if a is None or b is None:
        return True
    if len(a) == 1 and len(b) > 0:
        return a.lower() == b[0].lower()
    elif len(b) == 1 and len(a) > 0:
        return b.lower() == a[0].lower()
    else:
        return remove_diacritics(a).lower() == remove_diacritics(b).lower()


def to_plain_name(name):
    """
    Converts a :class:`Name` instance to a pair of
    (firstname,lastname)
    """
    return (name.first, name.last)


def deduplicate_words(words, separators):
    """
    Remove name duplicates in a list of words
    """
    seen = set()
    cleaned_words = []
    cleaned_seps = []
    for idx, w in enumerate(words):
        wl = w.lower()
        if wl not in seen:
            if len(wl) >= 3:
                seen.add(wl)
            cleaned_words.append(w)
            if idx < len(separators):
                cleaned_seps.append(separators[idx])
    if len(cleaned_words):
        cleaned_seps = cleaned_seps[:len(cleaned_words)-1]
    return cleaned_words, cleaned_seps

# Name normalization function used by the OAI proxy
nn_separator_re = re.compile(r',+ *')
nn_escaping_chars_re = re.compile(r'[\{\}\\]')
nn_nontext_re = re.compile(r'[^a-z_]+')
nn_final_nontext_re = re.compile(r'[^a-z_]+$')


def name_normalization(ident):
    ident = remove_diacritics(ident).lower()
    ident = ident.strip()
    ident = nn_separator_re.sub('_', ident)
    ident = nn_escaping_chars_re.sub('', ident)
    ident = nn_final_nontext_re.sub('', ident)
    ident = nn_nontext_re.sub('-', ident)
    return ident


def name_signature(first, last):
    ident = iunaccent(last.strip())
    ident = nn_escaping_chars_re.sub('', ident)
    ident = nn_final_nontext_re.sub('', ident)
    ident = nn_nontext_re.sub('-', ident)
    if len(first):
        ident = iunaccent(first[0])+'-'+ident
    return ident

### Name similarity measure ###

weight_initial_match = 0.4
weight_full_match = 0.8


def weight_first_name(word):
    if len(word) > 1:
        return weight_full_match
    else:
        return weight_initial_match


def weight_first_names(name_pair):
    a, b = name_pair
    return min(weight_first_name(a), weight_first_name(b))


def name_similarity(a, b):
    """
    Returns a float: how similar are these two names?
    Examples:

    >>> int(10*name_similarity(('Robin', 'Ryder'),('Robin', 'Ryder')))
    8
    >>> int(10*name_similarity(('Robin', 'Ryder'),('R.', 'Ryder')))
    4
    >>> int(10*name_similarity(('R.', 'Ryder'),('R.', 'Ryder')))
    4
    >>> int(10*name_similarity(('Robin J.', 'Ryder'),('R.', 'Ryder')))
    3
    >>> int(10*name_similarity(('Robin J.', 'Ryder'),('R. J.', 'Ryder')))
    8
    >>> int(10*name_similarity(('R. J.', 'Ryder'),('J.', 'Ryder')))
    3
    >>> int(10*name_similarity(('Robin', 'Ryder'),('Robin J.', 'Ryder')))
    7
    >>> int(10*name_similarity(('W. Timothy','Gowers'), ('Timothy','Gowers')))
    7
    >>> int(10*name_similarity(('Robin K.','Ryder'), ('Robin J.', 'Ryder')))
    0
    >>> int(10*name_similarity(('Claire', 'Mathieu'),('Claire', 'Kenyon-Mathieu')))
    0
    >>> int(10*name_similarity(('Amanda P.','Brown'),('Patrick','Brown')))
    0
    """

    if not a or not b or len(a) != 2 or len(b) != 2:
        return False
    firstA, lastA = a
    firstB, lastB = b
    firstA = iunaccent(firstA)
    firstB = iunaccent(firstB)
    lastA = iunaccent(lastA)
    lastB = iunaccent(lastB)
    if lastA != lastB:
        return 0.
    partsA, sepsA = split_name_words(firstA)
    partsB, sepsB = split_name_words(firstB)
    parts = zip(partsA, partsB)
    if not all(map(match_first_names, parts)):
        # Try to match in reverse
        partsA.reverse()
        partsB.reverse()
        parts = zip(partsA, partsB)
        if not all(map(match_first_names, parts)):
            return 0.

    maxlen = max(len(partsA), len(partsB))
    sumscores = 0
    expanded = []
    for i in range(maxlen):
        if i < len(parts):
            sumscores += weight_first_names(parts[i])
            expanded.append((len(partsA[i]) > 1, len(partsB[i]) > 1))
        elif i < len(partsA):
            sumscores -= 0.25*weight_first_name(partsA[i])
            expanded.append((len(partsA[i]) > 1, False))
        else:
            sumscores -= 0.25*weight_first_name(partsB[i])
            expanded.append((False, len(partsB[i]) > 1))

    # Make sure expanded first names of A are included in that of B
    # or that of B and included in that of A
    # This prevents ('Amanda P.','Brown') and ('A. Patrick','Brown')
    # frow matching
    if not (all([wa or not wb for wa, wb in expanded]) or
            all([wb or not wa for wa, wb in expanded])):
        return 0.

    sumscores = max(min(sumscores, 1), 0)
    return sumscores


def shallower_name_similarity(a, b):
    """
    Same as name_similarity, but accepts differences in the last names.
    This heuristics is more costly but is only used to attribute an ORCID
    affiliation to the right author in papers fetched from ORCID.
    (in the next function)
    """
    if not a or not b or len(a) != 2 or len(b) != 2:
        return False
    firstA, lastA = a
    firstB, lastB = b

    # Matching last names
    lastA = iunaccent(lastA)
    lastB = iunaccent(lastB)
    wordsA, sepA = split_name_words(lastA)
    wordsB, sepB = split_name_words(lastB)
    wordsA = set(wordsA)
    wordsB = set(wordsB)
    if not wordsA or not wordsB:
        return False
    ratio = float(len(wordsA & wordsB)) / len(wordsA | wordsB)

    partsA, sepsA = split_name_words(firstA)
    partsB, sepsB = split_name_words(firstB)
    partsA = [ p[0] for p in partsA ]
    partsB = [ p[0] for p in partsB ]

    parts = zip(partsA, partsB)
    if not all(map(match_first_names, parts)):
        # Try to match in reverse
        partsA.reverse()
        partsB.reverse()
        parts = zip(partsA, partsB)
        if not all(map(match_first_names, parts)):
            return 0.

    maxlen = max(len(partsA), len(partsB))
    return ratio*(len(parts)+1)/(maxlen+1)

def most_similar_author(ref_name, authors):
    """
    Given a name, compute the index of the most similar name
    in the authors list, if there is any compatible name.
    (None otherwise)
    """
    max_sim_idx = None
    max_sim = 0.
    for idx, name in enumerate(authors):
        cur_similarity = shallower_name_similarity(name, ref_name)
        if cur_similarity > max_sim:
            max_sim_idx = idx
            max_sim = cur_similarity
    return max_sim_idx


#### Helpers for the name splitting heuristic ######

# Is this string a name initial?


def contains_initials(s):
    # TODO delete the following commented dead code
    return len(s) == 1  # initial_re.search(iunaccent(s)) != None

# Is this word fully capitalized?


def is_fully_capitalized(s):
    return lowercase_re.search(remove_diacritics(s)) == None
# Split a word according to a predicate


def predsplit_forward(predicate, words):
    first = []
    last = []
    predHolds = True
    for i in range(len(words)):
        if predicate(i) and predHolds:
            first.append(words[i])
        else:
            predHolds = False
            last.append(words[i])
    return (first, last)
# The same, but backwards


def predsplit_backwards(predicate, words):
    first = []
    last = []
    predHolds = True
    for i in reversed(range(len(words))):
        if predicate(i) and predHolds:
            last.insert(0, words[i])
        else:
            predHolds = False
            first.insert(0, words[i])
    return (first, last)


###### Name splitting heuristic based on name_tools ######

def parse_comma_name(name):
    """
    Parse a name of the form "Last name, First name" to (first name, last name)
    Try to do something reasonable if there is no comma.
    """
    if ',' in name:
        # In this case name_tools does it well
        prefix, first_name, last_name, suffix = name_tools.split(name)
    else:
        words, separators = split_name_words(name)
        if not words:
            return ('', '')
        first_name = None
        last_name = None
        from_lists = True

        # Search for initials in the words
        initial = map(contains_initials, words)
        capitalized = map(is_fully_capitalized, words)

        # CASE 1: the first word is capitalized but not all of them are
        # we assume that it is the first word of the last name
        if not initial[0] and capitalized[0] and not all(capitalized):
            (last, first) = predsplit_forward(
                    (lambda i: capitalized[i] and not initial[i]),
                    words)

        # CASE 2: the last word is capitalized but not all of them are
        # we assume that it is the last word of the last name
        elif not initial[-1] and capitalized[-1] and not all(capitalized):
            (first, last) = predsplit_forward(
                    (lambda i: (not capitalized[i]) or initial[i]),
                    words)

        # CASE 3: the first word is an initial
        elif initial[0]:
            (first, last) = predsplit_forward(
                    (lambda i: initial[i]),
                    words)

        # CASE 4: the last word is an initial
        # this is trickier, we know that the last name comes first
        # but we don't really know where it stops.
        # For simplicity we assume that all the words in the first
        # name are initials
        elif initial[-1]:
            (last, first) = predsplit_backwards(
                    (lambda i: initial[i]),
                    words)

        # CASE 5: there are initials in the name, but neither
        # at the beginning nor at the end
        elif True in initial:
            last_initial_idx = None
            for i in range(len(words)):
                if initial[i]:
                    last_initial_idx = i
            first = words[:last_initial_idx+1]
            last = words[last_initial_idx+1:]

        # CASE 6: we have no clue
        # We fall back on name_tools, where wise things are done
        # to parse correctly names such as "Colin de la Higuera"
        else:
            prefix, first_name, last_name, suffix = name_tools.split(name)
            from_lists = False

        if from_lists:
            first_name = ' '.join(first)
            last_name = ' '.join(last)

    first_name = first_name.strip()
    last_name = last_name.strip()
    first_name = normalize_name_words(first_name)
    last_name = normalize_name_words(last_name)

    if not last_name:
        first_name, last_name = last_name, first_name

    return (first_name, last_name)

### Name unification heuristics ###


def zipNone(lstA, lstB):
    """
    Just as zip(), but pads with None the shortest list so that the list lengths match
    """
    la = len(lstA)
    lb = len(lstB)

    def aux():
        for i in range(max(la, lb)):
            objA, objB = None, None
            if i < la:
                objA = lstA[i]
            if i < lb:
                objB = lstB[i]
            yield (objA, objB)
    return list(aux())


def num_caps(a):
    """
    Number of capitalized letters
    """
    return sum(1 if c.isupper() else 0 for c in a)

def normalize_last_name(last):
    """
    Removes diacritics and hyphens from last names
    for comparison
    """
    return remove_diacritics(last.replace('-',' ')).lower()

def name_unification(a, b):
    """
    Returns the unified name of two matching names

    :param a: the first name pair (pair of unicode strings)
    :param b: the second name pair (idem)
    :returns: a unified name pair.
    """
    firstA, lastA = a
    firstB, lastB = b

    if normalize_last_name(lastA) != normalize_last_name(lastB):
        return None

    wordsA, sepsA = split_name_words(firstA)
    wordsB, sepsB = split_name_words(firstB)

    def keep_best(pair):
        a, b = pair
        if a is None:
            return b
        elif b is None:
            return a
        elif len(a) < len(b):
            return b
        elif len(b) < len(a):
            return a
        elif num_caps(b) < num_caps(a):
            return a
        elif num_caps(a) < num_caps(b):
            return b
        else:
            return a

    words = zipNone(wordsA, wordsB)
    seps = zipNone(sepsA, sepsB)
    best_words = None
    if all(map(match_first_names, words)):
        # Forward match
        best_words = map(keep_best, words)
        best_seps = map(keep_best, seps)
    else:
        wordsA.reverse()
        wordsB.reverse()
        sepsA.reverse()
        sepsB.reverse()
        words = zipNone(wordsA, wordsB)
        seps = zipNone(sepsA, sepsB)
        if all(map(match_first_names, words)):
            # Backward match
            best_words = map(keep_best, words)
            best_words.reverse()
            seps.reverse()
            best_seps = map(keep_best, seps)

    if best_words is not None:
        best_words, best_seps = deduplicate_words(best_words, best_seps)
        firstUnified = rebuild_name(best_words, best_seps)
        return firstUnified, lastA

    # No match
    return None


def unify_name_lists(a, b):
    """
    Unify two name lists, by matching compatible names and unifying them, and inserting the other names as they are.
    The names are sorted by average rank in the two lists.

    :returns: the unified list of pairs: the first component is the unified name (a pair itself),
              the second is the pair of indices from the original lists this name was created from
              (None when there is no corresponding name in one of the lists).
    """
    # TODO some normalization of last names? for instance case, hyphens…
    a = sorted(enumerate(a), key=lambda (idx, (first, last)): (last, first))
    b = sorted(enumerate(b), key=lambda (idx, (first, last)): (last, first))

    iA = 0
    iB = 0
    lenA = float(len(a))
    lenB = float(len(b))
    result = []
    while iA < len(a) or iB < len(b):
        if iA == len(a):
            idxB = b[iB][0]
            rankB = (idxB+1)/lenB
            result.append((b[iB][1], (rankB+1)/lenB, (None, idxB)))
            iB += 1
        elif iB == len(b):
            idxA = a[iA][0]
            rankA = (idxA+1)/lenA
            result.append((a[iA][1], (rankA+1)/lenA, (idxA, None)))
            iA += 1
        else:
            idxA = a[iA][0]
            idxB = b[iB][0]
            nameA = a[iA][1]
            nameB = b[iB][1]
            rankA = (idxA+1)/lenA
            rankB = (idxB+1)/lenB

            unified = name_unification(nameA, nameB)
            if unified is not None:
                # Those two names seem to refer to the same person
                # and we managed to unify the names.
                result.append((unified, 0.5*(rankA+rankB), (idxA, idxB)))
                iA += 1
                iB += 1
            elif shallower_name_similarity(nameA, nameB) > 0.:
                # They still look like the same person but for some
                # reason we fail to unify their name, let's default
                # to one of them.
                result.append((nameA, rankA, (idxA, idxB)))
                iA += 1
                iB += 1
            elif nameA[1] == nameB[1]:
                # Those two names look incompatible because of their first names
                result.append((nameA, rankA, (idxA, None)))
                result.append((nameB, rankB, (None, idxB)))
                iA += 1
                iB += 1
            elif nameA[1] < nameB[1]:
                result.append((nameA, rankA, (idxA, None)))
                iA += 1
            else:
                result.append((nameB, rankB, (None, idxB)))
                iB += 1

    result = [(name, idx) for name, _, idx in sorted(result, key=lambda x: x[1])]

    def make_unique(lst):
        seen = set()
        for name, idx in lst:
            first, last = name
            [k1, k2] = sorted([first.lower(), last.lower()])
            if (k1, k2) not in seen:
                seen.add((k1, k2))
                yield (name, idx)
            else:
                yield (None, idx)

    return list(make_unique(result))
