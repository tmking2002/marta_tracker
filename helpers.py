import requests
from datetime import datetime, timezone
import pandas as pd

from google.transit import gtfs_realtime_pb2

MARTA_RAIL_URL = "https://developerservices.itsmarta.com:18096/itsmarta/railrealtimearrivals/developerservices/traindata"

# Bus feeds are public GTFS-realtime protobuf -- no API key needed, unlike rail.
# NOTE: this is intentionally http://, not https://. MARTA's published docs
# list an https:// URL, but that host's TLS setup is broken (confirmed both
# by our own 403 and by other developers reporting SSL errors against it).
# The https:// URL 301-redirects to this exact http:// URL anyway, so we
# just go straight there and skip the broken hop.
MARTA_BUS_VEHICLE_URL = "http://gtfs-rt.itsmarta.com/TMGTFSRealTimeWebService/vehicle/"

REQUEST_TIMEOUT = 15  # seconds -- fail fast instead of hanging indefinitely on a stalled connection

def fetch_train_data(api_key):
    response = requests.get(MARTA_RAIL_URL, params={"apiKey": api_key}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()

def load_bus_routes(routes):
    """route_id -> human-readable route short name, for every route (bus + rail).
    Bus route_ids are looked up against this when logging positions so you don't
    have to join back to GTFS static data every time you want to know which
    bus route a row belongs to."""
    r = routes.copy()
    r['route_id'] = r['route_id'].astype(str).map(clean_id)
    return dict(zip(r['route_id'], r['route_short_name']))

def fetch_bus_positions(route_lookup=None):
    """Pull the current snapshot of all active bus vehicle positions.

    Returns a list of dicts, one per vehicle, already normalized to a shape
    close to the rail records so the same db insert pattern works for both.
    route_lookup is the dict from load_bus_routes(); if a route_id isn't
    found there, route_name falls back to the raw route_id.
    """
    response = requests.get(MARTA_BUS_VEHICLE_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)

    route_lookup = route_lookup or {}
    positions = []
    for entity in feed.entity:
        if not entity.HasField('vehicle'):
            continue

        v = entity.vehicle
        if not v.HasField('position'):
            continue

        route_id = clean_id(v.trip.route_id) if v.HasField('trip') else None

        positions.append({
            "vehicle_id": v.vehicle.id or entity.id,
            "trip_id": v.trip.trip_id if v.HasField('trip') else None,
            "route_id": route_id,
            "route_name": route_lookup.get(route_id, route_id),
            "lat": v.position.latitude,
            "lon": v.position.longitude,
            "bearing": v.position.bearing if v.position.HasField('bearing') else None,
            "speed": v.position.speed if v.position.HasField('speed') else None,
            "current_stop_id": v.stop_id or None,
            "current_stop_sequence": v.current_stop_sequence or None,
            # GTFS-rt timestamps are unix epoch seconds -- convert to the same
            # ISO string shape the rail side uses, so downstream code doesn't
            # need to care which vehicle type a row came from.
            "event_time": datetime.fromtimestamp(v.timestamp, tz=timezone.utc).isoformat() if v.timestamp else None,
        })

    return positions

def parse_delay_seconds(delay_str):
    # strip leading T and trailing S
    return int(delay_str[1:-1])  

def parse_event_time(event_time_str):
    return datetime.strptime(event_time_str, "%m/%d/%Y %I:%M:%S %p")

def clean_id(value):
    s = str(value).strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s

def dedupe_trains(records):
    # only keep the most recent train snapshot
    latest = {}
    for record in records:
        train_id = record['TRAIN_ID']

        if not train_id or record.get("IS_REALTIME") != "true":
            continue

        event_time = parse_event_time(record['EVENT_TIME'])

        if train_id not in latest or event_time > parse_event_time(latest[train_id]["EVENT_TIME"]):
            latest[train_id] = record

    return latest

def load_stations(stops):
    s = stops[(stops["location_type"] == 1) & (~stops["stop_name"].str.contains('RIDE'))].copy()
    s['stop_id'] = s['stop_id'].astype(str).map(clean_id)
    return list(zip(s['stop_id'], s['stop_name'], s['stop_lat'].astype(float), s['stop_lon'].astype(float)))

def load_station_lines(routes, trips, stops, stop_times):

    r = routes.copy()
    r['line'] = r['route_short_name'].str.upper()
    r = r[r['line'].isin(['RED', 'GREEN', 'GOLD', 'BLUE'])]
    r['route_id'] = r['route_id'].astype(str).map(clean_id)
    route_to_line = r[['route_id', 'line']]

    t = trips.copy()
    t['route_id'] = t['route_id'].astype(str).map(clean_id)
    t['trip_id'] = t['trip_id'].astype(str).map(clean_id)
    trip_to_line = t.merge(route_to_line, on='route_id')[['trip_id', 'line']]

    s = stops.copy()
    s['stop_id'] = s['stop_id'].astype(str).map(clean_id)
    s['parent_station'] = s['parent_station'].fillna('').astype(str).map(clean_id)
    stop_to_parent = s[s['parent_station'].ne('') & s['parent_station'].ne('nan')][['stop_id', 'parent_station']]

    st = stop_times.copy()
    st['trip_id'] = st['trip_id'].astype(str).map(clean_id)
    st['stop_id'] = st['stop_id'].astype(str).map(clean_id)

    merged = st.merge(trip_to_line, on='trip_id').merge(stop_to_parent, on='stop_id')
    grouped = merged.groupby('parent_station')['line'].agg(lambda x: sorted(set(x)))
    return grouped.to_dict()

def load_rail_lines(routes, trips, shapes):

    r = routes.copy()
    r['line'] = r['route_short_name'].str.upper()
    r = r[r['line'].isin(['RED', 'GREEN', 'GOLD', 'BLUE'])]
    route_to_line = dict(zip(r['route_id'], r['line']))

    # each route has multiple trips (direction + schedule variations), just take the most common
    t = trips[trips['route_id'].isin(route_to_line.keys())].copy()
    t['line'] = t['route_id'].map(route_to_line)
    shape_counts = t.groupby(['line', 'shape_id']).size().reset_index(name='count')
    best_idx = shape_counts.groupby('line')['count'].idxmax()
    best_shape = shape_counts.loc[best_idx]
    line_to_shape_id = dict(zip(best_shape['line'], best_shape['shape_id']))

    # collect the points for the four shape_ids
    necessary_shape_ids = set(line_to_shape_id.values())
    filtered_shapes = shapes[shapes['shape_id'].isin(necessary_shape_ids)].sort_values(['shape_id', 'shape_pt_sequence'])

    line_shapes = {}
    for line_name, shape_id in line_to_shape_id.items():
        pts = filtered_shapes[filtered_shapes['shape_id'] == shape_id]
        line_shapes[line_name] = list(zip(pts['shape_pt_lat'].astype(float), pts['shape_pt_lon'].astype(float)))

    return line_shapes