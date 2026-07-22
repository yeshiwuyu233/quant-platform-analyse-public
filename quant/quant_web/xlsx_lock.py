# /root/sop/xlsx_lock.py
"""xlsx 文件锁 — 所有读写操作必须通过此类。"""
import fcntl
import os

if os.path.exists("/var/www/quant/Whole Market.xlsx"):
    XLSX_PATH = "/var/www/quant/Whole Market.xlsx"
elif os.path.exists("/app/Whole Market.xlsx"):
    XLSX_PATH = "/app/Whole Market.xlsx"
else:
    XLSX_PATH = "/var/www/quant/Whole Market.xlsx"  # fallback


class XLSXLock:
    """独占锁（写入用，阻塞直到拿到锁）。"""
    def __init__(self, path=XLSX_PATH):
        self.path = path
        self.fd = None

    def __enter__(self):
        self.fd = open(self.path, "rb")
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self.fd

    def __exit__(self, *args):
        if self.fd:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.fd.close()


class XLSXReadLock:
    """共享锁（读取用，不阻塞其他读取）。"""
    def __init__(self, path=XLSX_PATH):
        self.path = path
        self.fd = None

    def __enter__(self):
        self.fd = open(self.path, "rb")
        fcntl.flock(self.fd, fcntl.LOCK_SH)
        return self.fd

    def __exit__(self, *args):
        if self.fd:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.fd.close()
