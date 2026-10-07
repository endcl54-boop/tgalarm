"""架構守門測試（S1 起，docs/modularization-plan.md 依賴規則鎖死）：
- core 唔准 import 任何域模組
- 域模組只准相對 import（`.`／`.core`）；絕對 tgalarm.* 同兄弟域全禁
- core／域唔准拉 telegram 進門（要喺冇 python-telegram-bot 環境都 import 得到）
- zipapp 打包＋bot.py shim zipimport 後備鏈（終態排練：得 bot.py＋bot.pyz 都行到）
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


class TestArchRules(unittest.TestCase):
    """依賴規則（藍圖拍板：域只准 core、域互不准）。"""

    def test_core_never_imports_domains(self):
        """core import 完，sys.modules 不得出現任何其他 tgalarm 子模組。"""
        code = ("import sys; import tgalarm.core; "
                "bad = [m for m in sys.modules if m.startswith('tgalarm.') "
                "and not m.startswith('tgalarm.core')]; "
                "assert not bad, bad; print('CORE_CLEAN')")
        r = subprocess.run([PY, "-c", code], cwd=REPO, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CORE_CLEAN", r.stdout)

    def test_domains_relative_core_only(self):
        """域模組（tgalarm/ 直下 .py）：
        - 絕對 `tgalarm.*` import 全禁（要相對）
        - 相對淨准 `.`／`.core`（兄弟域禁）
        """
        tdir = os.path.join(REPO, "tgalarm")
        domains = [f for f in os.listdir(tdir)
                   if f.endswith(".py") and f != "__init__.py"]
        self.assertIn("finance.py", domains)   # S1 第一域必在
        for fname in domains:
            src = open(os.path.join(tdir, fname), encoding="utf-8").read()
            mods = re.findall(r"^\s*(?:from|import)\s+([\w.]+)",
                              src, re.MULTILINE)
            bad_abs = [m for m in mods if m.startswith("tgalarm")]
            bad_sib = [m for m in mods
                       if m.startswith(".") and m not in (".", ".core")]
            self.assertFalse(bad_abs, f"{fname} 禁絕對 import：{bad_abs}")
            self.assertFalse(bad_sib, f"{fname} 禁兄弟域 import：{bad_sib}")

    def test_no_telegram_dependency_below_app(self):
        """core／域 import 唔拉 telegram——最終 app.py 先准碰。"""
        code = ("import sys; import tgalarm.core; import tgalarm.finance; "
                "bad = [m for m in sys.modules if m == 'telegram' "
                "or m.startswith('telegram.')]; "
                "assert not bad, bad; print('NO_TELEGRAM')")
        r = subprocess.run([PY, "-c", code], cwd=REPO, capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NO_TELEGRAM", r.stdout)


class TestRegistry(unittest.TestCase):
    """strangler 接縫：fire／formatter 註冊表（S2/S3 起有消費者）。"""

    def test_register_decorators(self):
        from tgalarm import core

        @core.register_fire("unit_test_x")
        async def _h(job, now):
            return None

        @core.register_formatter("unit_test_x")
        def _f(job):
            return "x"

        self.assertIs(core.FIRE_HANDLERS["unit_test_x"], _h)
        self.assertIs(core.JOB_FORMATTERS["unit_test_x"], _f)
        del core.FIRE_HANDLERS["unit_test_x"]
        del core.JOB_FORMATTERS["unit_test_x"]


class TestZipapp(unittest.TestCase):
    """打包＋終態排練：得 bot.py＋bot.pyz 嘅目錄都要行到（S13 部署態）。"""

    def test_pack_and_shim_rehearsal(self):
        pyz = os.path.join(tempfile.mkdtemp(), "bot.pyz")
        r = subprocess.run([PY, os.path.join(REPO, "pack.py"), pyz],
                           cwd=REPO, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(pyz))
        # 終態排練：臨時目錄得 bot.py＋bot.pyz（冇 tgalarm/ 目錄）→ zipimport 後備
        tmp = tempfile.mkdtemp()
        try:
            shutil.copy(os.path.join(REPO, "bot.py"), tmp)
            shutil.copy(pyz, tmp)
            probe = ("import bot; "
                     "assert bot._findef_route('層數') == ('status', {}); "
                     "assert bot._findef_route('使咗 20')[0] == 'expense'; "
                     "assert bot._findef_route('活動完 2.5') == "
                     "('stop', {'mins': '2.5'}); "
                     "print('REHEARSAL_OK')")
            r2 = subprocess.run([PY, "-c", probe], cwd=tmp,
                                capture_output=True, text=True)
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertIn("REHEARSAL_OK", r2.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
