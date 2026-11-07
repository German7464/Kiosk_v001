# Advisory LAN discovery v1 — implementation contract

Coordinator-selected additive mechanism for approved R5.1/R5.2/R18/R22 stage5. This is an implementation contract, not evidence of implementation, Android support or stage acceptance. Coordinator owns this file. Existing device-delivery-v1 authority, enrollment, bootstrap and receipt formats remain unchanged.

## Wire and bounds

IPv4 UDP limited broadcast destination255.255.255.255 port47751. No subnet scanning, internet rendezvous, multicast dependency, automatic routing/firewall changes or fallback to insecure HTTP. Windows and Android use the same datagrams; actual interface/broadcast availability must be demonstrated separately on both platforms. A timeout is an empty result with manual-address fallback, never proof there is no server.

One explicit search owns one ephemeral UDP socket, lasts at most3 seconds, sends at most3 queries with the same cryptographically random16-byte lowercase-hex nonce. Query UTF-8 JSON: {"protocol":"kiosk-discovery-v1","type":"query","nonce":"<32 lowercase hex>"}, padded with ASCII spaces to exactly512 bytes. No other fields. Receive buffers detect and discard oversize/truncated datagrams. Strict parsing rejects duplicate keys, wrong types, malformed UTF-8 and unexpected fields.

An explicitly enabled server replies unicast to the sender IP/ephemeral port, at most512 bytes: {"protocol":"kiosk-discovery-v1","type":"reply","nonce":"<matching nonce>","origin":"https://<configured address>:<port>","label":"<public installation label>"}. No other fields. Label is at most64 printable Unicode characters, no controls; validate total encoded size. Origin uses the existing native exact HTTPS-origin validator. An endpoint not representable within these limits is a configuration error. Never infer an advertised address from an arbitrary request field. Configure exactly one advertised reachable HTTPS origin, do not guess from VPN adapters. Listener bind/port conflict fails visibly without terminating the existing HTTPS server.

Responder is opt-in and owned by the normal server lifecycle, with bounded cancellation/cleanup, no separate dispatcher/service/task. At most one reply per source IPv4 per second and32 replies total per second, bounded256-entry source bookkeeping. Invalid requests receive no response. Response size never exceeds query size. No public enumeration of device registrations, authority materials, credentials, keys or content. Test configuration only; no deployment or installed-server enablement implied.

## Security and client behavior

Every result is an UNTRUSTED hint, including nonce-matched replies. Nonce correlation prevents stale accidental matches; it is not sender authentication. Display label/origin as escaped plain text. Deduplicate by exact origin, cap32 entries, retain only during the search/selection window. Never send enrollment, credentials or public bootstrap automatically to a discovered endpoint. Never import trust, accept a signing key from discovery, open a browser or fetch any URL just because it appeared.

Explicit selection only fills the manual-address input of an unconfigured connection. Existing independent public-bootstrap SHA256/facts confirmation and authenticated TLS/native pairing remain mandatory. Selecting a mismatched origin is rejected by the existing manual flow before enrollment. Saved configurations and accepted content are never replaced by discovery. Search cancellation/window close closes its socket; repeated clicks cannot fork concurrent searches or block the UI. No result explains how to enter a manual address. Android will use the same authority separation and its own physical acceptance after server/Windows review.

## Evidence boundary

Focused parser/limits/cancellation/security tests plus real two-host broadcast/query/reply and Windows selection into existing pairing are required for the Windows outcome. Loopback/direct-unicast fixtures are not LAN-broadcast acceptance. Failure due to existing VPN/firewall/interface policy is reported precisely; no settings bypass or inferred Android support. Cross-platform completion additionally requires the later real Android USB-device journey. Current status only in [the ledger](../../docs/TZ_PROGRESS.md).
