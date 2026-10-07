#!/usr/bin/env python3
"""zipapp 打包：淨包 tgalarm/（liar.py 等 S5+ 先入），產物 bot.pyz。

用法：python3 pack.py [輸出路徑]（預設 ./bot.pyz）
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "bot.pyz")


def main() -> None:
    stage = tempfile.mkdtemp(prefix="tgalarm_pack_")
    try:
        shutil.copytree(os.path.join(REPO, "tgalarm"),
                        os.path.join(stage, "tgalarm"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        if os.path.exists(os.path.join(REPO, "liar.py")):
            shutil.copy(os.path.join(REPO, "liar.py"),
                        os.path.join(stage, "liar.py"))
        subprocess.run(
            [sys.executable, "-m", "zipapp", stage, "--output", OUT,
             "--main", "tgalarm.app:main", "--python", "/usr/bin/env python3"],
            check=True)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    print(f"bot.pyz 打包完成：{OUT}（{os.path.getsize(OUT)} bytes）")


if __name__ == "__main__":
    main()
