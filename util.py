def is_surrogate(s, i):
    if 0xD800 <= ord(s[i]) <= 0xDBFF:
        try:
            l = s[i + 1]
        except IndexError:
            return False
        if 0xDC00 <= ord(l) <= 0xDFFF:
            return True
        else:
            raise ValueError("Illegal UTF-16 sequence: %r" % s[i:i + 2])
    else:
        return False

def uslice(s, start, end):
    l = len(s)
    i = 0
    while i < start and i < l:
        if is_surrogate(s, i):
            start += 1
            end += 1
            i += 1
        i += 1
    while i < end and i < l:
        if is_surrogate(s, i):
            end += 1
            i += 1
        i += 1
    return s[start:end]

flatten = lambda l: [item for sublist in l for item in sublist]

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
