# Session Service

## Login
Users sign in with email and password. On success the service issues an access token valid for 15 minutes and a refresh token valid for 30 days.

## Refresh
The client exchanges a refresh token for a new access token. Each refresh issues a new refresh token and the old one stops working.

## Logout
Logout deletes the stored refresh token. The access token remains usable until it expires.

## Password changes
Changing a password revokes all existing refresh tokens for that user. Every other device must sign in again once its access token expires.
