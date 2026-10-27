# maya_subDtoNURBS

将 Maya **SubD / 多边形控制笼**转成接近 Plasticity 风格的 **NURBS 面片**（每笼四边面一张光滑补丁），并导出工业 CAD 常用的 **STEP (`.stp`)**（无 OpenCascade 时回退 **IGES**）。

目标环境：**Maya 2018**（Python 2.7），同时尽量兼容更新版 Maya。

---

## 它解决什么问题？

在 Maya 里按 `3`，只是视口里的 **Smooth Mesh Preview**，工业软件读不懂。本工具不是把密网格每个小面都变成 NURBS，而是：

```
选中控制笼（四边面）
    → 纯 Python Catmull-Clark 细分 N 级（默认 2 → 5×5 采样）
    → 每个原始四边面 → 一张双三次 NURBS（逼近 SubD 极限）
    → 导出 .stp / .igs
```

---

## 目录结构

```
maya_subDtoNURBS/
├── README.md
├── launch.py                 # Script Editor 一键开 UI
├── install_shelf.py          # 往当前 Shelf 加按钮
├── plug-ins/
│   └── maya_subDtoNURBS_plugin.py
└── maya_subDtoNURBS/
    ├── __init__.py
    ├── constants.py
    ├── core/
    │   ├── smooth_extract.py # 提取/烘焙平滑网格
    │   ├── mesh_to_nurbs.py  # 多边形 → NURBS 面片
    │   ├── step_export.py    # STP / IGES 导出
    │   └── pipeline.py       # 串联流水线
    ├── ui/
    │   └── window.py         # 简易界面
    └── utils/
        └── maya_helpers.py
```

---

## 安装与启动

路径已放在 Maya 用户脚本目录下时，一般无需改 `MAYA_SCRIPT_PATH`。

### 方式 A：最快（推荐先试）

1. 打开 Maya → **Script Editor** → Python
2. 任选其一执行：

```python
# 推荐（最稳，不经过 execfile / __file__）
import sys
root = r"d:\My Documents\maya\2018\zh_CN\scripts\maya_subDtoNURBS"
if root not in sys.path:
    sys.path.insert(0, root)
for _n in sorted(list(sys.modules.keys()), reverse=True):
    if _n == "maya_subDtoNURBS" or _n.startswith("maya_subDtoNURBS."):
        sys.modules.pop(_n, None)
from maya_subDtoNURBS.utils.text_encoding import fix_maya_default_encoding
fix_maya_default_encoding()
from maya_subDtoNURBS.ui import show_ui
show_ui()
```

```python
# 或用 launch.py（内部已去掉 __file__）
execfile(r"d:\My Documents\maya\2018\zh_CN\scripts\maya_subDtoNURBS\launch.py")
```

Maya 2022+（Python 3）可用：

```python
exec(open(r"d:\My Documents\maya\2018\zh_CN\scripts\maya_subDtoNURBS\launch.py", encoding="utf-8").read())
```

### 方式 B：Shelf 按钮

```python
execfile(r"d:\My Documents\maya\2018\zh_CN\scripts\maya_subDtoNURBS\install_shelf.py")
```

### 方式 C：Plug-in Manager

1. 把 `plug-ins` 目录加入 `MAYA_PLUG_IN_PATH`（或复制到 `maya/2018/plug-ins`）
2. **Window → Settings/Preferences → Plug-in Manager** 勾选 `maya_subDtoNURBS_plugin.py`
3. 命令行：

```python
import maya.cmds as cmds
cmds.subDtoNURBS()                          # 开 UI
cmds.subDtoNURBSConvert()                   # 只转换当前选择
cmds.subDtoNURBSConvert(f="D:/out/part.stp", l=2, t="stp")  # 转换并导出
```

| 参数 | 含义 |
|------|------|
| `-f` / `filepath` | 导出路径 |
| `-l` / `level` | 平滑次数，`2` ≈ 按 `3` |
| `-t` / `type` | `stp` / `iges` / `both` |

---

## 使用步骤

1. 选中一个**四边面为主**的控制笼（不要用已 polySmooth 炸开的密网格当笼，除非你有意）
2. 打开工具 UI
3. 模式选 **cage — CC极限补丁**；**CC级数** 默认 `2`（5×5 CV）
4. 可先点 **仅转换为 NURBS** 检查场景结果
5. 再点 **转换并导出…** 选择保存路径

---

## 关于 STEP / IGES 导出

Maya 2018 中文版通常**没有**名为 `IGES` 的导出器（会报「指定的文件类型无效」），正确名称多为 `IGES_ATF Export`，且常需 ATF/DirectConnect 插件。

本插件导出优先级（**默认不走 Maya ATF**）：

| 格式 | 顺序 |
|------|------|
| **STEP `.stp`** | OpenCascade（可选）→ **内置纯 Python STEP 写入** |
| **IGES `.igs`** | **内置纯 Python IGES（Entity 128）写入** |

> **崩溃说明：** Maya 2018 的 `IGES_ATF` / ATF 导出在部分环境下会**直接把 Maya 打崩**（不是 Python 报错，无法 catch）。因此默认已禁用 ATF。若你明确要试，可设环境变量 `MAYA_SUBD_USE_ATF=1`（有风险）。

即使没有 OCC、Maya 也没有 CAD 插件，仍可导出可被多数工业软件读取的 `.stp` / `.igs`。

可选增强（更高保真 B-Rep）：

```bash
pip install OCP
# 或 pip install pythonocc-core
```

---

## 算法说明（对齐 Plasticity 的思路）

Plasticity 并不是把「按 3 平滑后的密网格」每个小面都变成 NURBS，而是：

```
控制笼四边面（蓝线拓扑）
    → 每张四边面 → 一张双三次 NURBS（逼近 SubD 极限曲面）
    → 导出 STEP
```

所以导出后面片数量 ≈ **笼上面数**，而不是细分后的几千面。

### 本插件默认模式 `cage`（推荐，重写）

| 步骤 | 模块 | 做法 |
|------|------|------|
| 1 | `cc_subdivide` | 纯 Python Catmull-Clark + 每原始面 UV 追踪 |
| 2 | `subd_to_nurbs` | 每笼四边面取出 `(2^N+1)²` 网格 → loft / surface 双三次 NURBS |
| 3 | `cad_writers` | 纯 Python 写 `.stp` / `.igs` |

| CC级数 | 每面控制点 | 说明 |
|--------|------------|------|
| 1 | 3×3 | 快，偏粗 |
| 2（默认） | 5×5 | 推荐 |
| 3 | 9×9 | 更贴极限，更重 |

相关经典算法：Catmull-Clark 规则区 ↔ 双三次 B 样条；Loop & Schaefer / Stam；商业：Plasticity Convert、Alias、Rhino ToNURBS。

### 旧模式 `legacy`

先 `polySmooth` 聚密，再一面一片——面片爆炸，仅作对比。

---

## 限制与后续路线图

- [ ] 跨面片 **G1 / G2** 缝合
- [ ] 不规则点精确极限求值（Stam）替代均匀采样
- [ ] 自动重拓扑 / 只保留四边面
- [ ] OpenCascade 封闭 B-Rep
- [ ] STEP 单位 / 图层头信息

建模建议：尽量用**全四边面**控制笼，硬边与细分权重先整理好再导出。

---

## 代码调用示例

```python
import sys
sys.path.insert(0, r"d:\My Documents\maya\2018\zh_CN\scripts\maya_subDtoNURBS")

from maya_subDtoNURBS.core import convert_and_export, run_conversion

# 只转 NURBS（CC 极限补丁）
run_conversion(mode="cage", cc_levels=2)

# 转换并导出
convert_and_export(
    filepath=r"D:/export/my_part.stp",
    mode="cage",
    cc_levels=2,
    export_format="stp",   # stp | iges | both
)
```

---

## 版本

- **0.2.0** — 重写：CC 细分采样 → 每笼面一张光滑 NURBS（对齐 Plasticity 拓扑）
- **0.1.0** — 框架 + 旧聚密路径 + STP/IGES + UI

作者：RS-Sherry
