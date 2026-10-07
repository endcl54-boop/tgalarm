"""core：config／registry／共用底層。唔准 import 任何域模組（守門測試鎖）。"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("tgalarm.core")


# ---------------- 設定（環境變數 > 設定檔；同 bot.py 舊制一字不差） ----------------

def read_config_file(config_path: str) -> dict:
    """讀 KEY=VALUE 設定檔（# 註釋行略過、值剝引號）。"""
    cfg: dict = {}
    try:
        with open(config_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("讀唔到設定檔 %s：%s", config_path, e)
    return cfg


def config_get(key: str, default: str = "") -> str:
    """環境變數優先，跟設定檔（TGALARM_CONFIG 可換路徑）。"""
    v = os.environ.get(key, "").strip()
    if v:
        return v
    path = os.path.expanduser(
        os.environ.get("TGALARM_CONFIG", "~/.tgalarm/config"))
    return read_config_file(path).get(key, default).strip()


# ---------------- Registry（strangler 接縫；S2/S3 起有第一批消費者） ----------------

# job type -> async fn(job, now)；_fire_later 逐步由 if 鏈改行呢張表
FIRE_HANDLERS: dict = {}

# job type -> fn(job) -> str；_fmt_job_content 同樣逐步註冊表化
JOB_FORMATTERS: dict = {}


def register_fire(jtype: str):
    """域模組用：@register_fire("takeaway_on") 註冊到點處理器。"""
    def deco(fn):
        FIRE_HANDLERS[jtype] = fn
        return fn
    return deco


def register_formatter(jtype: str):
    """域模組用：@register_formatter("takeaway_on") 註冊 job 內容格式。"""
    def deco(fn):
        JOB_FORMATTERS[jtype] = fn
        return fn
    return deco
