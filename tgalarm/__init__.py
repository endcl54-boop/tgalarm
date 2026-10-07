"""tgalarm — 模組化套件（2026-10-07 拍板：按功能域切＋zipapp 部署）。

依賴規則（test_arch.py 鎖死）：
    core/   唔准 import 任何域模組
    域模組  只准 from . import core；域之間唔准互相 import
"""
