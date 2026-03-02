import time
from collections import deque

class ROIStats:
    def __init__(self, maxlen=5000):
        self.start = time.time()
        self.times = deque(maxlen=maxlen)
        self.sums = deque(maxlen=maxlen)

    def add_sample(self, value: float):
        t = time.time() - self.start
        self.times.append(t)
        self.sums.append(value)
