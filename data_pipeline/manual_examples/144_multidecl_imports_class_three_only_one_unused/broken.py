import logging
import threading
import queue


class Worker:
    def __init__(self):
        self.lock = threading.Lock()
        self.tasks = queue.Queue()

    def log_status(self):
        print("worker running")
