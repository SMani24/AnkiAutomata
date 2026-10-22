"""Run blocking work off Tk's thread and deliver results when the GUI polls."""

from queue import Empty, Queue
from threading import Event, Thread


class BackgroundTasks:
    def __init__(self, workers=3):
        self.jobs = Queue(maxsize=20)
        self.results = Queue()
        self.closed = Event()
        for _ in range(workers):
            Thread(target=self._work, daemon=True).start()

    def submit(self, operation, success, failure):
        self.jobs.put_nowait((operation, success, failure))

    def _work(self):
        while not self.closed.is_set():
            try:
                operation, success, failure = self.jobs.get(timeout=0.1)
            except Empty:
                continue
            try:
                result = operation()
                callback = success
            except Exception as error:
                result = error
                callback = failure
            if not self.closed.is_set():
                self.results.put((callback, result))

    def poll(self):
        for _ in range(20):
            if self.closed.is_set():
                return
            try:
                callback, result = self.results.get_nowait()
            except Empty:
                return
            callback(result)

    def close(self):
        self.closed.set()
