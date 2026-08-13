#!/bin/sh
set -ex

# This Entrypoint used inside Docker Compose only

export WAIT_HOSTS=$API_HOST:$API_PORT

# Use envsubst to create the actual replacements_values.sed file with values from env vars
envsubst < replacements.sed > replacements_values.sed

# In production we should replace some values in generated JS code
sed -i -f replacements_values.sed *.js

# nginx resolves an upstream hostname ONCE, at startup, and caches the address
# for the life of the worker. On a platform that gives a service a new private
# address every time it redeploys — Railway does — that cached address goes
# stale the moment the API is redeployed, and every proxied request then hangs
# until it times out. Static files keep serving from disk throughout, so the
# dashboard loads and only the data is missing, which reads like a broken API
# rather than a broken proxy.
#
# Resolving per request fixes it, but that needs an explicit resolver: nginx
# will not read /etc/resolv.conf for this. Take the first nameserver from it,
# bracketing IPv6 addresses as the resolver directive requires.
NGINX_RESOLVER=$(awk '/^nameserver/ { print ($2 ~ /:/) ? "[" $2 "]" : $2; exit }' /etc/resolv.conf)
export NGINX_RESOLVER="${NGINX_RESOLVER:-127.0.0.11}"

# We need to copy nginx.conf to correct place
envsubst '${API_HOST} ${API_PORT} ${NGINX_RESOLVER}' < /etc/nginx/conf.d/compose.conf.template > /etc/nginx/nginx.conf

# In Docker Compose we should wait other services start
./wait

exec "$@"
