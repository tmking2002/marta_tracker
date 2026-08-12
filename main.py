# python -m http.server 8000

import os
import pandas as pd

from looper import loop
from helpers import load_rail_lines, load_stations, load_station_lines
from web_export import write_static_layers, write_page

def main():

    gtfs_dir = 'marta_gtfs'

    routes = pd.read_csv(f'{gtfs_dir}/routes.txt')
    trips = pd.read_csv(f'{gtfs_dir}/trips.txt')
    stops = pd.read_csv(f'{gtfs_dir}/stops.txt')
    stop_times = pd.read_csv(f'{gtfs_dir}/stop_times.txt')
    shapes = pd.read_csv(f'{gtfs_dir}/shapes.txt')

    api_key = os.environ.get('marta-api-key')
    interval = 5
    output_dir = 'tracker_files'
    iterations = 100
    line_shapes = load_rail_lines(routes, trips, shapes)
    stations = load_stations(stops)
    station_lines = load_station_lines(routes, trips, stops, stop_times)

    print(len(station_lines), list(station_lines.items())[:3])

    write_static_layers(output_dir, line_shapes, stations, station_lines)
    write_page(output_dir, interval)

    loop(api_key, interval, output_dir, iterations)

if __name__ == '__main__':
    main()