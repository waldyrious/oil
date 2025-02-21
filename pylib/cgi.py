"""
cgi.py - Copied from Python stdlib.

We don't want the side effects of importing tempfile, which imports random,
which opens /dev/urandom!
"""

def escape(s, quote=False):
    # type: (str, bool) -> str
    '''Replace special characters "&", "<" and ">" to HTML-safe sequences.
    If the optional flag quote is true, the quotation mark character (")
    is also translated.'''
    s = s.replace("&", "&amp;") # Must be done first!
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    if quote:
        s = s.replace('"', "&quot;")
    return s
