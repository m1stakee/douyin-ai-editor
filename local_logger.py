import logging
import re
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOGGER_NAME = "videoflow"
_SECRET = re.compile(r"(?i)(bearer\s+|(?:api[_ -]?key|license[_ -]?key|token|password)\s*[:=]\s*)[^\s,;]+")
_secrets = set()
_lock = threading.RLock()
_context = ContextVar('log_context', default={})
_logging_error = ''

def register_secrets(values):
    if isinstance(values, dict):
        for key, value in values.items():
            if re.search(r'(?i)key|token|secret|password|authorization|signature|policy', str(key)):
                if isinstance(value, str) and value:
                    with _lock:
                        _secrets.add(value)
                        if value.lower().startswith('bearer '): _secrets.add(value[7:])
            elif isinstance(value, (dict, list)): register_secrets(value)
    elif isinstance(values, list):
        for value in values: register_secrets(value)

@contextmanager
def context(**values):
    token = _context.set({**_context.get(), **values})
    try: yield
    finally: _context.reset(token)

class SafeFormatter(logging.Formatter):
    def format(self, record):
        return _safe(super().format(record))

class LocalFileHandler(RotatingFileHandler):
    def handleError(self, record):
        global _logging_error
        _logging_error = _safe(str(sys.exc_info()[1]))

def logging_error():
    return _logging_error

def log_directory() -> Path:
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return root / "logs"

def _safe(value: object) -> str:
    text = _SECRET.sub(lambda match: match.group(1) + "<REDACTED>", str(value))
    with _lock: secrets = sorted(_secrets, key=len, reverse=True)
    for secret in secrets: text = text.replace(secret, '<REDACTED>')
    text = re.sub(r'https?://[^\s\"\'<>]+', lambda m: m.group(0).split('?')[0].split('#')[0], text)
    text = re.sub(r'(?i)\b(?:sk-[a-z0-9_-]+|VF-[a-z0-9-]+)', '<REDACTED>', text)
    return text

def get_logger() -> logging.Logger:
    with _lock:
        return _get_logger()

def _get_logger() -> logging.Logger:
    global _logging_error
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    try:
        directory = log_directory()
        directory.mkdir(parents=True, exist_ok=True)
        handler = LocalFileHandler(directory / "videoflow.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(SafeFormatter("%(asctime)s [%(levelname)s] [pid=%(process)s %(threadName)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        _logging_error = ''
    except OSError as exc:
        _logging_error = str(exc)
        logger.addHandler(logging.NullHandler())
    return logger

def info(message: object, *args: object) -> None:
    get_logger().info('%s %s', _context.get(), str(message) % args if args else str(message))

def error(message: object, *args: object, exc_info: bool = False) -> None:
    get_logger().error('%s %s', _context.get(), str(message) % args if args else str(message), exc_info=exc_info)

def request(call, url, **kwargs):
    register_secrets(kwargs.get('headers', {})); register_secrets(kwargs.get('json', {}))
    request_id = uuid.uuid4().hex[:12]; started = time.monotonic()
    body = kwargs.get('json') or {}
    info('http.start request=%s url=%s model=%s timeout=%s', request_id, url, body.get('model', ''), kwargs.get('timeout'))
    try:
        response = call(url, **kwargs)
        info('http.end request=%s status=%s elapsed=%.3fs request_id=%s retry_after=%s', request_id, response.status_code,
             time.monotonic()-started, response.headers.get('x-request-id', ''), response.headers.get('Retry-After', ''))
        if isinstance(response.status_code, int) and response.status_code >= 400:
            error('http.error request=%s body=%s', request_id, _safe(response.text)[:2000])
        return response
    except Exception:
        error('http.exception request=%s elapsed=%.3fs', request_id, time.monotonic()-started, exc_info=True)
        raise

def install_exception_hooks():
    sys.excepthook = lambda kind, value, tb: error('uncaught exception', exc_info=(kind, value, tb))
    threading.excepthook = lambda args: error('uncaught thread=%s', args.thread.name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
