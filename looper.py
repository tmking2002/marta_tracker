import time
import traceback

from helpers import fetch_train_data, dedupe_trains, fetch_bus_positions
from web_export import write_trains
from db import insert_positions, insert_bus_positions

BUS_POLL_INTERVAL_SECONDS = 30  # MARTA's bus feed only updates server-side about this often anyway --
                                 # polling faster gained nothing and likely triggered rate-limiting/
                                 # blackholing on their end (same connect-timeout symptom either way).

def loop(api_key, interval_seconds, output_dir, iterations, conn, route_lookup=None):
    count = 0
    last_bus_poll = 0  # forces a bus poll on the very first iteration

    while iterations is None or count < iterations:
        try:
            records = fetch_train_data(api_key)
            latest_trains = dedupe_trains(records)
            write_trains(output_dir, latest_trains)

            inserted = insert_positions(conn, latest_trains)
            print(f"[{count}] Rail: updated {output_dir} with {len(latest_trains)} trains ({inserted} new rows logged)")
        except Exception as e:
            print(f"[{count}] Rail loop failed: {e}")
            traceback.print_exc()

        now = time.time()
        if now - last_bus_poll >= BUS_POLL_INTERVAL_SECONDS:
            last_bus_poll = now
            try:
                # Separate try/except from rail: the bus feed is a different host
                # entirely (gtfs-rt.itsmarta.com vs developerservices.itsmarta.com),
                # so an outage on one side shouldn't stop logging the other.
                bus_positions = fetch_bus_positions(route_lookup)
                bus_inserted = insert_bus_positions(conn, bus_positions)
                print(f"[{count}] Bus: saw {len(bus_positions)} vehicles ({bus_inserted} new rows logged)")
            except Exception as e:
                print(f"[{count}] Bus loop failed: {e}")
                traceback.print_exc()

        count += 1
        if iterations is None or count < iterations:
            time.sleep(interval_seconds)