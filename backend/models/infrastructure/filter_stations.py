import osmium as osm
import sys

class StationFilter(osm.SimpleHandler):
    def __init__(self):
        super(StationFilter, self).__init__()
        self.writer = osm.SimpleWriter("data/raw/stations_europe.osm.pbf")

    def node(self, n):
        if self._is_station(n):
            self.writer.add_node(n)

    def way(self, w):
        if self._is_station(w):
            self.writer.add_way(w)

    def relation(self, r):
        if self._is_station(r):
            self.writer.add_relation(r)

    def _is_station(self, o):
        tags = o.tags
        return (
            tags.get("railway") in ("station", "halt")
        )

def main(input_file):
    handler = StationFilter()
    handler.apply_file(input_file, locations=True, idx='flex_mem')
    handler.writer.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python filter_stations.py <input.pbf>")
        sys.exit(1)
    main(sys.argv[1])