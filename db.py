import sqlite3
from datetime import datetime, timezone

from helpers import parse_delay_seconds

SCHEMA = """
CREATE TABLE IF NOT EXISTS train_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    train_id TEXT NOT NULL,
    event_time TEXT NOT NULL,   -- MARTA's own EVENT_TIME string, as returned by the API
    poll_time TEXT NOT NULL,    -- when we fetched this record, ISO 8601 UTC
    line TEXT,
    direction TEXT,
    destination TEXT,
    station TEXT,
    waiting_time TEXT,
    delay_seconds INTEGER,
    lat REAL,
    lon REAL,
    UNIQUE(train_id, event_time)
);

CREATE INDEX IF NOT EXISTS idx_train_positions_train_id ON train_positions(train_id);
CREATE INDEX IF NOT EXISTS idx_train_positions_station ON train_positions(station);
CREATE INDEX IF NOT EXISTS idx_train_positions_event_time ON train_positions(event_time);

CREATE TABLE IF NOT EXISTS bus_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT NOT NULL,
    event_time TEXT,             -- from the feed's vehicle timestamp; can be NULL if the feed omits it
    poll_time TEXT NOT NULL,     -- when we fetched this record, ISO 8601 UTC -- use this if event_time is NULL
    trip_id TEXT,
    route_id TEXT,
    route_name TEXT,
    lat REAL,
    lon REAL,
    bearing REAL,
    speed REAL,
    current_stop_id TEXT,
    current_stop_sequence INTEGER,
    -- Note: if the feed ever omits a vehicle's timestamp (event_time IS NULL),
    -- SQLite treats NULLs as distinct in UNIQUE constraints, so those rows
    -- won't dedupe against each other -- you'd get one row per poll for that
    -- vehicle instead of one row per real update. Fine as a fallback, but
    -- worth knowing if you see a vehicle with a suspiciously high row count.
    UNIQUE(vehicle_id, event_time)
);

CREATE INDEX IF NOT EXISTS idx_bus_positions_vehicle_id ON bus_positions(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_bus_positions_route_id ON bus_positions(route_id);
CREATE INDEX IF NOT EXISTS idx_bus_positions_event_time ON bus_positions(event_time);
"""


def get_connection(db_path):
    conn = sqlite3.connect(db_path)
    # WAL mode lets you run read queries (e.g. from a notebook) against the
    # db file *while* the collector is still writing to it.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path):
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def insert_positions(conn, train_records):
    """Log one poll's worth of train positions.

    train_records: dict of train_id -> raw MARTA record, exactly what
    dedupe_trains() returns. The UNIQUE(train_id, event_time) constraint
    means re-inserting a train whose EVENT_TIME hasn't changed since the
    last poll is a no-op (INSERT OR IGNORE) -- so you can call this every
    5 seconds without bloating the table with duplicate rows for trains
    that haven't produced a new event yet.

    Returns the number of genuinely new rows written.
    """
    rows = []
    for train_id, record in train_records.items():
        if not record.get('LATITUDE'):
            continue

        delay_seconds = parse_delay_seconds(record["DELAY"]) if record.get("DELAY") else 0

        rows.append((
            train_id,
            record['EVENT_TIME'],
            datetime.now(timezone.utc).isoformat(),
            record.get('LINE'),
            record.get('DIRECTION'),
            record.get('DESTINATION'),
            record.get('STATION'),
            record.get('WAITING_TIME'),
            delay_seconds,
            float(record['LATITUDE']),
            float(record['LONGITUDE']),
        ))

    if not rows:
        return 0

    cur = conn.executemany(
        """INSERT OR IGNORE INTO train_positions
           (train_id, event_time, poll_time, line, direction, destination,
            station, waiting_time, delay_seconds, lat, lon)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return cur.rowcount


def insert_bus_positions(conn, bus_records):
    """Log one poll's worth of bus positions.

    bus_records: list of dicts, exactly what fetch_bus_positions() returns.
    Same INSERT OR IGNORE dedup pattern as insert_positions() -- a vehicle
    whose event_time hasn't changed since the last poll is a no-op.
    """
    rows = []
    poll_time = datetime.now(timezone.utc).isoformat()
    for record in bus_records:
        if record.get('lat') is None or record.get('lon') is None:
            continue

        rows.append((
            record['vehicle_id'],
            record.get('event_time'),
            poll_time,
            record.get('trip_id'),
            record.get('route_id'),
            record.get('route_name'),
            record['lat'],
            record['lon'],
            record.get('bearing'),
            record.get('speed'),
            record.get('current_stop_id'),
            record.get('current_stop_sequence'),
        ))

    if not rows:
        return 0

    cur = conn.executemany(
        """INSERT OR IGNORE INTO bus_positions
           (vehicle_id, event_time, poll_time, trip_id, route_id, route_name,
            lat, lon, bearing, speed, current_stop_id, current_stop_sequence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return cur.rowcount