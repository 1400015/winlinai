"""Generic signal-based worker for the Qt track.

Replaces QMetaObject.invokeMethod(...string slot name...) with typed signals:
callables run in a daemon thread and report back via `finished`/`failed`.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

try:
    from PySide6 import QtCore
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


if QT_AVAILABLE:
    class Worker(QtCore.QObject):
        """Runs a callable in a background thread and emits the result.

        Usage:
            worker = Worker()
            worker.finished.connect(self._on_done)
            worker.failed.connect(self._on_error)
            start_worker(worker, func, arg1, kw=2)
        """
        finished = QtCore.Signal(object)   # (result,)
        failed = QtCore.Signal(object)     # (exception,)

        def run_callable(self, func, *args, **kwargs):
            try:
                result = func(*args, **kwargs)
            except Exception as error:  # noqa: BLE001 - reported via signal
                logger.error("Worker callable failed: %s", type(error).__name__)
                self.failed.emit(error)
            else:
                self.finished.emit(result)

    def start_worker(worker, func, *args, **kwargs):
        """Start `func` in a daemon thread, reporting to `worker`'s signals."""
        thread = threading.Thread(
            target=worker.run_callable, args=(func, *args), kwargs=kwargs,
            daemon=True, name="qt-worker")
        thread.start()
        return thread
else:
    class Worker:  # type: ignore[no-redef]
        """Stub so module import works without PySide6."""
        pass

    def start_worker(worker, func, *args, **kwargs):
        raise RuntimeError("PySide6 is required for Worker")
