# -*- coding: utf-8 -*-
"""快速打开 UI。在 Script Editor 执行本文件。

注意: Maya 的 execfile 不提供 __file__，此处故意不用 __file__。
"""

from __future__ import absolute_import, print_function

import sys

# 固定包根目录（不要用 __file__，execfile 会炸）
ROOT = r"d:\My Documents\maya\2018\zh_CN\scripts\maya_subDtoNURBS"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 强制重载，确保改代码后立即生效
for name in sorted(list(sys.modules.keys()), reverse=True):
    if name == "maya_subDtoNURBS" or name.startswith("maya_subDtoNURBS."):
        sys.modules.pop(name, None)

from maya_subDtoNURBS.utils.text_encoding import fix_maya_default_encoding

fix_maya_default_encoding()

from maya_subDtoNURBS.ui import show_ui

show_ui()
