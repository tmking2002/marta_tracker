import requests
from datetime import datetime
import pandas as pd

MARTA_RAIL_URL = "https://developerservices.itsmarta.com:18096/itsmarta/railrealtimearrivals/developerservices/traindata"

def fetch_train_data(api_key):
    response = requests.get(MARTA_RAIL_URL, params={"apiKey": api_key})
    response.raise_for_status()
    return response.json()

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
    stations = []
    for _, stop in stops.iterrows():
        if stop["location_type"] == 1 and 'RIDE' not in stop['stop_name']:
            stations.append((clean_id(stop['stop_id']), stop["stop_name"], float(stop["stop_lat"]), float(stop["stop_lon"])))
    return stations

def load_station_lines(routes, trips, stops, stop_times):

    route_to_line = {}
    for _, route in routes.iterrows():
        name = route['route_short_name'].upper()
        if name in ['RED', 'GREEN', 'GOLD', 'BLUE']:
            route_to_line[clean_id(route['route_id'])] = name

    trip_to_line = {}
    for _, trip in trips.iterrows():
        route_id = clean_id(trip['route_id'])
        if route_id in route_to_line:
            trip_to_line[clean_id(trip['trip_id'])] = route_to_line[route_id]

    stop_to_parent = {}
    for _, stop in stops.iterrows():
        parent_id = clean_id(stop.get('parent_station', ''))
        if parent_id and parent_id != 'nan':
            stop_to_parent[clean_id(stop['stop_id'])] = parent_id

    station_lines = {}
    for _, st in stop_times.iterrows():
        line = trip_to_line.get(clean_id(st['trip_id']))
        parent_id = stop_to_parent.get(clean_id(st['stop_id']))

        if not line or not parent_id:
            continue

        if parent_id not in station_lines:
            station_lines[parent_id] = set()

        station_lines[parent_id].add(line)

    return {parent_id: sorted(lines) for parent_id, lines in station_lines.items()}

def load_rail_lines(routes, trips, shapes):

    # get the four route ids
    route_to_line = {}
    for _, route in routes.iterrows():
        name = route['route_short_name'].upper()
 
        if name in ['RED', 'GREEN', 'GOLD', 'BLUE']:
            route_to_line[route['route_id']] = name
 
    # each route has multiple trips (direction + schedule variations), just take the most common
    shape_counts_by_route = {}
    for _, trip in trips.iterrows():
        route_id = trip['route_id']
 
        if route_id not in route_to_line:
            continue
 
        if route_id not in shape_counts_by_route:
            shape_counts_by_route[route_id] = {}
 
        shape_id = trip['shape_id']
 
        shape_counts_by_route[route_id][shape_id] = shape_counts_by_route[route_id].get(shape_id, 0) + 1
 
    # find the shape_id for each of the four routes
    line_to_shape_id = {}
    for route_id, counts in shape_counts_by_route.items():
        line_name = route_to_line[route_id]
        best_shape_id = max(counts, key=counts.get)
        line_to_shape_id[line_name] = best_shape_id
 
    # collect the points for the four shape_ids
    necessary_shape_ids = set(line_to_shape_id.values())
    points_by_shape = {}
    for _, point in shapes.iterrows():
        shape_id = point['shape_id']
 
        if shape_id in necessary_shape_ids:
 
            if shape_id not in points_by_shape:
                points_by_shape[shape_id] = []
 
            points_by_shape[shape_id].append((
                int(point["shape_pt_sequence"]),
                float(point["shape_pt_lat"]),
                float(point["shape_pt_lon"]),
            ))
 
    line_shapes = {}
    for line_name, shape_id in line_to_shape_id.items():
        ordered_points = sorted(points_by_shape[shape_id])
        line_shapes[line_name] = [(lat, lon) for _, lat, lon in ordered_points]
 
    return line_shapes