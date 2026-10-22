# Webhook Delivery

## Sending events
The service posts each event as JSON to the subscriber's URL and expects a 2xx response within 10 seconds.

## Retries
If the subscriber does not answer with a 2xx response, the service retries the delivery up to 5 times over one hour, with growing delays.

## Signatures
Every request carries an HMAC signature header so the subscriber can verify that the event came from the service.

## Ordering
Events for the same object are delivered in the order they were created.

## Exhausted retries
After the fifth failed attempt the event is moved to a dead-letter list kept for 14 days, and an operator can replay it from the dashboard.
