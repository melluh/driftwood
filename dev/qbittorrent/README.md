# qBittorrent + ProtonVPN for testing

qBittorrent runs inside [gluetun](https://github.com/qdm12/gluetun)'s network namespace, so all of
its traffic goes through ProtonVPN (gluetun's firewall blocks anything else, also when the VPN
drops). Gluetun asks Proton for a forwarded port and sets it as qBittorrent's listening port.

```sh
cd dev/qbittorrent
cp .env.example .env      # set WIREGUARD_PRIVATE_KEY
mkdir -p data/downloads data/media/movies data/media/tv
docker compose up -d
docker compose logs -f gluetun   # wait for "port forwarded is ..."
```

The WebUI is at <http://localhost:8080>, bound to localhost only, and doesn't ask for a login: the
seeded config lets the compose network (172.30.0.0/24, which is where Docker's port publishing comes
from) skip authentication, and gluetun's port-forwarding hook relies on that too. Don't expose the
port beyond your machine. The seed is only written when `data/config` has no config yet; delete
`data/config` to start over.

## Pointing Driftwood at it

Keep the library roots next to the downloads (same filesystem) so imports are hardlinks. In
`backend/.env`, with `<repo>` the absolute path of this repository:

```sh
DRIFTWOOD_DOWNLOADS__QBITTORRENT__URL=http://localhost:8080
# No API key needed: qBittorrent lets this machine in without authentication.
DRIFTWOOD_DOWNLOADS__QBITTORRENT__PATH_MAPPINGS='[{"remote":"/downloads","local":"<repo>/dev/qbittorrent/data/downloads"}]'
DRIFTWOOD_LIBRARY__ROOTS='[{"name":"movies","path":"<repo>/dev/qbittorrent/data/media/movies","kind":"movies"},{"name":"tv","path":"<repo>/dev/qbittorrent/data/media/tv","kind":"tv"}]'
```

To test API key authentication as well, generate a key under Tools → Options → WebUI → API Key,
turn off "Bypass authentication for clients in whitelisted IP subnets", and set
`DRIFTWOOD_DOWNLOADS__QBITTORRENT__API_KEY`. (The forwarded-port hook keeps working: it comes from
localhost, which stays exempt.)

## Checks

```sh
docker exec driftwood-gluetun wget -qO- https://ipinfo.io     # a Proton IP, not yours
curl -s localhost:8080/api/v2/app/preferences | grep -o '"listen_port":[0-9]*'   # the forwarded port
```
