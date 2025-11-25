import logging
import queue
from datetime import datetime

class Logger:
    def __init__(self):
        self.log_queue = queue.Queue()
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    def log(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_message = f"{timestamp} - {message}"
        self.log_queue.put(formatted_message)
        logging.info(message)

    def get_messages(self):
        messages = []
        while not self.log_queue.empty():
            messages.append(self.log_queue.get_nowait())
        return messages
