#!/usr/bin/env python3
"""tgalarm 入口薄殼（S13 batch 終態，docs/modularization-plan.md）。
開發態：repo 有 tgalarm/ → import tgalarm.engine；
部署態：同目錄 bot.pyz → 插 sys.path 再 import。
bot.X 讀寫刪全部代理去 engine.X——引擎同測試共用一個命名空間，
monkeypatch 照舊生效（369 舊測試零改動過閘＝行為不變鐵證）。
"""
import os
import sys

try:
    from tgalarm import engine as _engine
except ImportError:                       # 部署態：得 bot.py＋bot.pyz
    _pyz = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.pyz")
    if os.path.exists(_pyz) and _pyz not in sys.path:
        sys.path.insert(0, _pyz)
    from tgalarm import engine as _engine


class _BotModule(sys.modules[__name__].__class__):
    """ModuleType 子類：屬性讀寫刪全部代理去 engine（PEP 562 手法）。"""

    def __getattr__(self, name):
        return getattr(_engine, name)

    def __setattr__(self, name, value):
        setattr(_engine, name, value)

    def __delattr__(self, name):
        delattr(_engine, name)


sys.modules[__name__].__class__ = _BotModule

if __name__ == "__main__":
    _engine.main()
