CREATE TABLE stops (
    stop_id        text PRIMARY KEY,
    stop_name      text NOT NULL,
    stop_lat       double precision,
    stop_lon       double precision,
    location_type  integer,
    parent_station text
);