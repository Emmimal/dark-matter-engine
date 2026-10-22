# Cart Service

## Reserving stock
When a customer adds an item, the service reserves one unit of stock for that customer. Reserved units are not shown as available to other shoppers.

## Checkout
At checkout the service converts each reservation into a sale and decrements the stock count by the reserved quantity.

## Out of stock
If an item has no available units, the add-to-cart call returns 409 with the message "out of stock".

## Price changes
If the price changes while an item sits in a cart, the cart shows the new price and notifies the customer at checkout.

## Abandoned carts
A reservation that is not checked out within 30 minutes is released and the unit becomes available again.
