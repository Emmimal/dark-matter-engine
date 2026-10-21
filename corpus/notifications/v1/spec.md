# Notification Service

## Sending
The service sends push notifications through the push provider API. Each request carries a notification_id.

## Rate limiting
Each user receives at most 5 notifications per hour. Notifications over the limit are dropped and counted in the metrics dashboard.

## Quiet hours
Between 22:00 and 07:00 in the user's local time, notifications are held and delivered at 07:00.
