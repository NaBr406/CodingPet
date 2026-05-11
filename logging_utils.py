from __future__ import annotations

import logging
from pathlib import Path


# 项目统一使用这个 logger 名称，方便各模块共享同一套日志配置。
LOGGER_NAME = "codingpet"

# 这里负责把运行日志同时写到文件和控制台，方便本地调试和打包后追踪。


def setup_logging(log_path: str | Path = "codingpet.log") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    # 同一个进程里可能多次调用初始化，先检查 handler 是否已经挂上，
    # 避免重复追加导致同一条日志被打印多次。
    if logger.handlers:
        return logger

    # 默认把日志写到当前工作目录；打包后可由调用方传入用户目录中的路径。
    target = Path(log_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    )

    # 文件和控制台共用同一套格式，方便对照排查线程、顺序和错误现场。
    logger.setLevel(logging.INFO)
    logger.propagate = False

    file_handler = logging.FileHandler(target, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger
