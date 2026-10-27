# -*- coding: utf-8 -*-
"""
Maya 2018 (Python 2) + zh_CN Windows string helpers.

- cmds UI: UTF-8 byte strings show as Latin-1 mojibake; prefer GBK/cp936 bytes.
- Exceptions from Chinese Maya often contain unicode; bare str(exc) raises
  UnicodeEncodeError under ascii defaultencoding — always use safe_str().
"""

from __future__ import absolute_import, print_function

import locale
import os
import sys

_PY2 = sys.version_info[0] < 3
if _PY2:
    _text_type = unicode  # noqa: F821
    _bytes_type = str
else:
    _text_type = str
    _bytes_type = bytes


def fix_maya_default_encoding():
    """Widen Py2 default encoding so unicode<->str is less fragile in Maya."""
    if not _PY2:
        return
    try:
        # reload(sys) is the classic Maya/Py2 workaround
        reload(sys)  # noqa: F821
        sys.setdefaultencoding("utf-8")
    except Exception:
        pass


def _preferred_encoding():
    for cand in (
        "gbk",
        "cp936",
        "mbcs",
        locale.getpreferredencoding(False),
        sys.getfilesystemencoding(),
    ):
        if cand:
            return cand
    return "gbk"


def to_unicode(text):
    if text is None:
        return u""
    if isinstance(text, _text_type):
        return text
    if isinstance(text, _bytes_type):
        for enc in ("utf-8", "gbk", "cp936", "mbcs", "latin-1"):
            try:
                return text.decode(enc)
            except Exception:
                continue
    try:
        return _text_type(text)
    except Exception:
        return u""


def safe_str(text):
    """Never raise UnicodeEncodeError; returns Py2 str / Py3 str."""
    if text is None:
        return ""
    if not _PY2:
        return text if isinstance(text, str) else str(text)
    if isinstance(text, _bytes_type):
        return text
    uni = to_unicode(text)
    for enc in ("utf-8", "gbk", "cp936", "mbcs"):
        try:
            return uni.encode(enc)
        except Exception:
            continue
    return uni.encode("utf-8", "replace")


def ui_text(text):
    """
    Value for maya.cmds labels / warnings / buttons.

    On Chinese Windows + Py2, default to GBK bytes (Maya zh_CN expects this).
    Set MAYA_SUBD_UI_UNICODE=1 to pass unicode instead.
    """
    uni = to_unicode(text)
    if not _PY2:
        return uni
    if os.environ.get("MAYA_SUBD_UI_UNICODE") == "1":
        return uni
    # Default: GBK for Maya 2018 zh_CN
    enc = _preferred_encoding()
    try:
        return uni.encode(enc)
    except Exception:
        return uni.encode("gbk", "replace")
