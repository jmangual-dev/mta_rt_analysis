-- schema/04_observations_nyct_columns.sql
-- NYCT extension fields, available after compiling gtfs-realtime-NYCT.proto.
-- is_assigned marks a trip assigned to a physical train; unassigned trips
-- are published but frequently never run.
-- trip_type is the first character of train_id (the trip type designator).

ALTER TABLE observations
  ADD COLUMN is_assigned boolean,
  ADD COLUMN train_id    text,
  ADD COLUMN trip_type   char(1);

ALTER TABLE vehicles
  ADD COLUMN is_assigned boolean,
  ADD COLUMN train_id    text,
  ADD COLUMN trip_type   char(1);