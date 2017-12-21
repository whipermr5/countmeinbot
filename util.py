"""Contains util functions"""

def is_surrogate(string, i):
    if 0xD800 <= ord(string[i]) <= 0xDBFF:
        try:
            char = string[i + 1]
        except IndexError:
            return False
        if 0xDC00 <= ord(char) <= 0xDFFF:
            return True
        else:
            raise ValueError("Illegal UTF-16 sequence: %r" % string[i:i + 2])
    else:
        return False

def uslice(string, start, end):
    length = len(string)
    i = 0
    while i < start and i < length:
        if is_surrogate(string, i):
            start += 1
            end += 1
            i += 1
        i += 1
    while i < end and i < length:
        if is_surrogate(string, i):
            end += 1
            i += 1
        i += 1
    return string[start:end]

def flatten(lst):
    return [item for sublist in lst for item in sublist]

def strip_html_symbols(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def make_html_bold(text):
    return '<b>' + strip_html_symbols(text) + '</b>'

def make_html_bold_first_line(text):
    text_split = text.split('\n', 1)
    output = make_html_bold(text_split[0])
    if len(text_split) > 1:
        output += '\n' + strip_html_symbols(text_split[1])
    return output

def make_emoji_for_option():
    # Emoji taken from http://unicode.org/emoji/charts/full-emoji-list.html
    return "&#x1F465;"
