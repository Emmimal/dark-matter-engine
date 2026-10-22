# Report Export

## Requesting an export
The client calls POST /exports with a date range. The service returns an export id immediately and builds the file in the background.

## Checking status
The client polls GET /exports/{id}, which returns pending, ready or failed.

## Download
When the status is ready, the file is available at the returned URL as a CSV.

## Limits
A date range longer than 366 days is rejected with a 422 response.
