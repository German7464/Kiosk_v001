# Standalone LAN Transport Protection

Status: approved design, not implemented or verified. Requirement: TZ 18.11, with related session and write protection under 18.4 and 18.8. This document defines a bounded stage 2 decision; it does not complete security or authorize later network stages.

## Current Application

The existing Flask/Waitress application serves HTTP. LAN startup can expose login, fullscreen password validation, session cookies, content, and media without transport protection. CSRF and password hashing do not prevent interception or modification in transit. Existing commands and runtime behavior are unchanged by this documentation stage.

## Threats and Trust Boundaries

Treat LAN peers, address discovery, DNS responses, and forwarded headers as untrusted. Protect against passive credential/session interception and active server impersonation or content modification between clients and the server. TLS does not prevent endpoint compromise, denial of service, malicious authorized edits, or theft of files by an account with operating-system access.

The operator establishes initial trust through a controlled local procedure. The server operating-system account, TLS proxy, and application on the same computer form the server trust boundary. The local certificate authority is a separate, more privileged trust boundary. No trust is established merely by discovering an address or accepting a browser warning.

## Connection Architecture

```text
Browser / display client
    -> HTTPS over LAN, validated server identity
    -> TLS reverse proxy on the server computer
    -> HTTP over loopback only
    -> single-process Waitress -> Flask -> local storage
```

- All routes, APIs, optimized media, and static assets use one HTTPS origin. Protect public display content as well as administrative credentials. Avoid mixed content and absolute HTTP links in the protected profile.
- Waitress binds exclusively to loopback in this profile; no LAN-accessible backend listener exists. The proxy is the only network entry point. Local processes remain inside the stated operating-system trust boundary.
- The protected LAN profile exposes no plaintext HTTP service and has no automatic downgrade when TLS fails. Users open the HTTPS address directly; an HTTP redirect is not a security boundary.
- Keep local HTTP development as a separate explicit profile. Do not enable it as an automatic recovery path for a protected deployment. Existing deployments are not silently reconfigured.
- A separate TLS proxy is approved as a necessary deployment component. This stage installs nothing and adds no dependency. Product selection, pinned version, license review, configuration, startup supervision, and packaging belong to the next bounded implementation/prototype stage. Waitress and Flask remain the application stack.

## Autonomous Certificate Trust

Every installation uses its own local certificate authority; no shared product-wide private key is distributed. Routine startup and HTTPS operation must not require Internet services, public DNS, public certificate issuance, or corporate infrastructure.

1. During controlled setup, create the installation authority and a distinct server key/certificate. The server certificate includes the exact operator-configured DNS names and/or IP addresses in its subject alternative names. A DNS name needs a working local resolution method; an IP address can be used without DNS when covered by the certificate.
2. Export only the public root certificate for clients. Obtain its SHA-256 fingerprint directly from the trusted setup console or a controlled offline record, and compare it through an independent channel before installing trust. Downloading a root and its fingerprint from the same unauthenticated endpoint does not establish identity.
3. The operator explicitly installs the verified root in the trust store actually used by each browser/client. Document and test platform-specific permissions and trust scope. Never install a root automatically from discovery or change an OS trust store without operator authorization.
4. Connect to the configured HTTPS address and verify chain, identity, and validity. Never disable verification or use a permanent browser-warning exception. A client that cannot enforce this trust model is unsupported until a tested alternative is separately approved.

Only the server leaf private key is needed for daily serving. Keep the authority private key outside the running application/proxy account in protected offline custody, with a protected independent recovery copy. Keep the server key restricted to the proxy service identity. Store secrets separately from executable resources and logs; never commit or include keys in diagnostics. No exact platform paths or certificate-generation implementation are introduced here.

## Renewal and Recovery

- Renew the server certificate before expiry using the same authority and validated address list. Stage and validate the certificate/key pair before switching; retain the last valid pair for rollback. Reject mismatched keys, invalid chains, and expired certificates without falling back to HTTP. Scheduling, cryptographic parameters, validity periods, and proxy reload mechanics must be specified with the selected implementation.
- Changing an IP address or name outside the existing certificate requires a new valid server certificate and an explicit client URL update. Network discovery cannot override certificate identity checks.
- Replacing a server key preserves root trust only when the authority remains trusted. If a server key is compromised, remove the compromised service from network access and replace the key/certificate. Do not claim that replacing a certificate revokes the old one on offline clients: until an enforced revocation mechanism exists, rotate the installation authority and remove old root trust from every admitted client before resuming protected service.
- Authority compromise requires new authority and server keys, independent fingerprint verification, removal of old trust from clients, and explicit re-enrollment. Do not accept an automatic trust update authenticated solely by the compromised authority.
- If the authority key is lost, an existing valid leaf may continue until expiry; renewal requires a new authority and client re-enrollment unless the protected recovery copy is restored. Loss of the server key requires controlled replacement. Wrong clocks can invalidate certificates: diagnose and correct time without disabling validation.
- TLS/proxy failure makes network service unavailable. Existing MVP clients have no guaranteed persistent offline snapshot; this design does not add offline behavior or claim uninterrupted display.

## Planned Application Integration Contract

These are future requirements, not current configuration options or implemented behavior.

- The protected profile requires an explicit external HTTPS origin and host allowlist, loopback backend binding, and Secure + HttpOnly + SameSite=Lax session cookies. All local launch URLs and readiness checks must respect the selected profile rather than reusing an unrelated HTTP server.
- The proxy validates the public Host, rejects unknown hosts, and removes client-provided forwarded metadata before setting its own canonical host/scheme and single client address. Its request-body bound must preserve the application's existing 20 MiB default or configured lower deployment limit.
- Waitress is the single forwarding-metadata interpreter: trust only the exact loopback proxy address, one proxy hop, and the necessary forwarded host/scheme/address metadata. Clear other forwarded metadata. Do not add a second ProxyFix layer or trust arbitrary proxies. Configure the proxy/backend address family explicitly so trust is not accidentally widened.
- Authentication limits use the client address produced by this trusted chain. A client cannot choose its budget with X-Forwarded-For, Forwarded, or a supplied username on password change. Keep the documented single-process limiter limitation; shared NAT clients can still share a budget.
- HTTP development retains its separate cookie/transport policy. The HTTPS profile must fail startup on inconsistent transport settings instead of silently serving credentials over HTTP. Final option names and CLI/configuration format are deferred to the implementation stage.
- No route, JSON schema, database migration, content-version change, or credential replacement is required by this design. Certificates authenticate the service, not users or group membership. Pairing, device authorization, replication, update signatures, and future client authentication remain separate work.

## Verification and Acceptance Plan

Use disposable data, test keys, a temporary authority, and isolated listeners. Never alter working credentials, trust stores, firewall rules, or user servers as an implicit test action.

| Scenario | Required result before implementation acceptance |
| --- | --- |
| Trusted server; Internet unavailable | Public pages/APIs/media and authenticated admin work over HTTPS without external calls. |
| Unknown authority, wrong address, expired certificate, invalid chain | Browser/client rejects the connection; no warning bypass or HTTP retry. |
| Missing key, mismatched pair, invalid proxy/profile configuration | Clear sanitized failure; no plaintext fallback and no secret output. |
| LAN connection to backend or plaintext service | Connection unavailable; verify listeners and test from another device. |
| Client-supplied forwarded headers | Proxy replaces them; scheme/host/client address cannot be selected by the client. |
| Multiple client addresses and repeated password checks | Correct independent per-source budgets; existing username/global-source limits and 429/Retry-After remain effective. |
| HTTPS login/session/fullscreen/change operations | Secure cookie attributes; current CSRF, session revocation, restart behavior, and 403 responses preserved. |
| Public navigation, refresh, previews, and image upload | No mixed content, working generated URLs, unchanged API formats, and preserved request/upload limits. |
| Certificate renewal, name change, and invalid replacement | Valid replacement works; invalid replacement preserves a valid service or fails closed; documented client URL changes work. |
| Authority replacement/compromise exercise | Old trust removed, independent verification repeated, old authority no longer accepted by admitted clients. |
| Windows browser and each target Android TV | Actual trust-store behavior, validity checks, renewal, and HTTPS fullscreen tested on recorded OS/browser versions. |

Automated checks should cover application/profile validation, trusted-header handling, cookie flags, route compatibility, and TLS failures using real HTTPS with a temporary authority. Browser checks must exercise actual trust behavior; Flask test-client HTTPS simulation alone cannot establish TLS correctness. Physical LAN and Android TV results must remain pending until performed. Record observed HTTP status codes only after successful TLS negotiation; certificate failures are not HTTP error responses.

## Stage Boundary and Next Work

This stage delivers the design only. Next select and evaluate a maintained Windows-compatible TLS proxy, define its exact certificate/profile/configuration contract, and prepare a separately scoped isolated HTTPS prototype. Do not deploy to user servers, install roots, change firewall rules, or claim section 18 complete from approval of this design.

References: [Waitress TLS limitation](https://docs.pylonsproject.org/projects/waitress/en/stable/), [Waitress reverse proxy handling](https://docs.pylonsproject.org/projects/waitress/en/stable/reverse-proxy.html), [Flask proxy trust](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/), and [Flask security guidance](https://flask.palletsprojects.com/en/stable/web-security/).
