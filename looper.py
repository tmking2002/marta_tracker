import time
import traceback

from helpers import fetch_train_data, dedupe_trains
from web_export import write_trains

def loop(api_key, interval_seconds, output_dir, iterations):
    count = 0

    while iterations is None or count < iterations:
        try:
            records = fetch_train_data(api_key)
            latest_trains = dedupe_trains(records)
            write_trains(output_dir, latest_trains)
            print(f"[{count}] Updated {output_dir} with {len(latest_trains)} trains")
        except Exception as e:
            print(f"[{count}] Loop failed: {e}")
            traceback.print_exc()

        count += 1
        if iterations is None or count < iterations:
            time.sleep(interval_seconds)