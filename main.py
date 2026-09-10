# python -m http.server 8000

import os
import pandas as pd

from looper import loop
from helpers import load_rail_lines, load_stations, load_station_lines, load_bus_routes
from web_export import write_static_layers, write_page
from db import init_db

def main():

    gtfs_dir = 'marta_gtfs'

    routes = pd.read_csv(f'{gtfs_dir}/routes.txt')
    trips = pd.read_csv(f'{gtfs_dir}/trips.txt')
    stops = pd.read_csv(f'{gtfs_dir}/stops.txt')
    stop_times = pd.read_csv(f'{gtfs_dir}/stop_times.txt')
    shapes = pd.read_csv(f'{gtfs_dir}/shapes.txt')

    api_key = os.environ.get('MARTA_API_KEY')
    interval = 5
    output_dir = 'tracker_files'
    iterations = None  # this is now a data collector, not a demo -- run until stopped
    db_path = 'marta_history.db'

    line_shapes = load_rail_lines(routes, trips, shapes)
    stations = load_stations(stops)
    station_lines = load_station_lines(routes, trips, stops, stop_times)
    route_lookup = load_bus_routes(routes)  # covers bus routes; rail rows just go unused here

    print(len(station_lines), list(station_lines.items())[:3])

    write_static_layers(output_dir, line_shapes, stations, station_lines)
    write_page(output_dir, interval)

    conn = init_db(db_path)
    loop(api_key, interval, output_dir, iterations, conn, route_lookup)

if __name__ == '__main__':
    main()