import requests
from google.transit import gtfs_realtime_pb2

URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs"

resp = requests.get(URL, timeout=10)
resp.raise_for_status()
print(f"{len(resp.content)} bytes")

feed = gtfs_realtime_pb2.FeedMessage()
feed.ParseFromString(resp.content)

print(f"header timestamp: {feed.header.timestamp}")
print(f"entities: {len(feed.entity)}")

for entity in feed.entity[:3]:
    print(entity)
