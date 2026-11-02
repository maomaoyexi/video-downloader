# -*- coding: utf-8 -*-
"""保留旧源码启动路径；当前实现由 v2.7.1 入口提供。"""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("视频下载工具v2.7.1-GUI.py")), run_name="__main__")
