import gzip
import logging
import time
import urllib.request
from datetime import datetime, timezone

import boto3

URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs"
BUCKET = "mta-rt-raw-jm3635"
INTERVAL = 30

logging.basicConfig(
    filename="poll.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

session = boto3.Session(profile_name="poller")
s3 = session.client("s3")


def poll():
    with urllib.request.urlopen(URL, timeout=10) as r:
        content = r.read()

    now = datetime.now(timezone.utc)
    key = f"raw/year={now:%Y}/month={now:%m}/day={now:%d}/hour={now:%H}/{int(now.timestamp())}.pb.gz"

    body = gzip.compress(content)
    s3.put_object(Bucket=BUCKET, Key=key, Body=body)
    logging.info(f"{key} {len(content)} -> {len(body)}")


if __name__ == "__main__":
    logging.info("poller started")
    while True:
        start = time.monotonic()
        try:
            poll()
        except Exception:
            logging.exception("poll failed")
        time.sleep(max(0, INTERVAL - (time.monotonic() - start)))
