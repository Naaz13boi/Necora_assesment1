import os
import sys
import time
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from confluent_kafka import Producer

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_SERVERS", "localhost:9092")
KAFKA_TOPIC = "code-changes"
TARGET_DIR = os.path.abspath("./target_code")

# Ensure the target directory exists
os.makedirs(TARGET_DIR, exist_ok=True)
print(f"[*] Watching directory: {TARGET_DIR}")

# Kafka delivery callback
def delivery_report(err, msg):
    if err is not None:
        print(f"[-] Message delivery failed: {err}")
    else:
        print(f"[+] Message delivered to {msg.topic()} [{msg.partition()}]")

class CodeWatcherHandler(FileSystemEventHandler):
    def __init__(self, producer):
        self.producer = producer

    def get_relative_path(self, path):
        return os.path.relpath(path, TARGET_DIR)

    def is_python_file(self, path):
        return path.endswith(".py") and not any(part.startswith(".") or part == "__pycache__" for part in path.split(os.sep))

    def send_event(self, action, path):
        if not self.is_python_file(path):
            return

        rel_path = self.get_relative_path(path)
        content = ""
        
        if action == "upsert":
            try:
                # Wait briefly for file write completion to avoid reading empty files
                time.sleep(0.1)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"[-] Error reading file {path}: {e}")
                return

        payload = {
            "file_path": rel_path,
            "content": content,
            "action": action,
            "timestamp": time.time()
        }

        try:
            self.producer.produce(
                KAFKA_TOPIC,
                key=rel_path.encode('utf-8'),
                value=json.dumps(payload).encode('utf-8'),
                callback=delivery_report
            )
            # Flush to trigger callbacks and write to broker immediately
            self.producer.flush()
            print(f"[>] Dispatched {action.upper()} event for: {rel_path}")
        except Exception as e:
            print(f"[-] Failed to produce event to Kafka: {e}")

    def on_any_event(self, event):
        print(f"[DEBUG] OS triggered event: {event.event_type} on path: {event.src_path}")

    def on_created(self, event):
        if not event.is_directory:
            self.send_event("upsert", event.src_path)
    

    def on_moved(self, event):
        if not event.is_directory:
            print(f"[*] Detected file move: from {event.src_path} to {event.dest_path}")
            self.send_event("upsert", event.dest_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.send_event("upsert", event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.send_event("delete", event.src_path)

def init_kafka_producer():
    conf = {
        'bootstrap.servers': KAFKA_BOOTSTRAP_SERVERS,
        'client.id': 'codebase-watcher',
        'acks': 'all',
        # Enable idempotence for reliable delivery
        'enable.idempotence': True
    }
    
    print(f"[*] Connecting to Kafka on {KAFKA_BOOTSTRAP_SERVERS}...")
    retries = 5
    while retries > 0:
        try:
            producer = Producer(conf)
            # Check connection by fetching metadata
            producer.list_topics(timeout=3.0)
            print("[+] Successfully connected to Kafka.")
            return producer
        except Exception as e:
            print(f"[-] Kafka connection failed. Retrying in 3 seconds... ({retries} left)")
            time.sleep(3)
            retries -= 1
            
    print("[-] Could not connect to Kafka. Please ensure your Docker containers are running.")
    sys.exit(1)

def main():
    producer = init_kafka_producer()
    
    event_handler = CodeWatcherHandler(producer)
    observer = Observer()
    observer.schedule(event_handler, path=TARGET_DIR, recursive=True)
    observer.start()

    print(f"[+] Real-time code watcher started. Modify files in '{TARGET_DIR}' to see events.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[*] Stopping code watcher...")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
