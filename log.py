import time

def log(*msg):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    print(timestamp, *msg, flush=True)
