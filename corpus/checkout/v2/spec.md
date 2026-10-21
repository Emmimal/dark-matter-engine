# Checkout API

## Initiating payment
The client sends POST /payments with an order_id and amount. The service calls the payment gateway and returns 201 with the payment record once the gateway confirms the charge.

## Declined cards
If the gateway declines the card, the service returns 402 with the decline reason. No payment record is stored and the order stays in the pending state.

## Retry on server errors
If the gateway responds with a 500 error, the service retries the charge up to 3 times with exponential backoff. After the third failure the service returns 502 to the client.

## Order storage
After a confirmed charge the service writes the order as paid in the orders table within the same request.

## Idempotency keys
Every POST /payments request must include an Idempotency-Key header. The service stores the key with the gateway result. If the client retries after a lost response, the service returns the stored result and never charges the order a second time.
