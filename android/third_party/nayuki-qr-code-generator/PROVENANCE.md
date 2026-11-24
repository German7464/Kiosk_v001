# Nayuki QR Code generator (vendored)

Source: <https://github.com/nayuki/QR-Code-generator> — Java library, MIT License.
Pinned commit: `bcfe1b018cec5f1f91b5705eca5bb4cdd34e9f8d` (committed 2026-10-29).

Copied byte-for-byte, package `io.nayuki.qrcodegen` unchanged, into
`android/app/src/main/java/io/nayuki/qrcodegen/`. No local modifications.
Each source file carries the upstream MIT permission notice in its header.

| File | Bytes | SHA-256 |
| --- | --- | --- |
| `QrCode.java` | 35238 | `01715baeb383ec26f7c38138299a2b6e5bbfa36fa607441c79dc9cc76b107c6b` |
| `QrSegment.java` | 12234 | `70f10e518d3a8f1a1862e598a249abaac036a9c6fae4e5892c4b6d24995bb8d7` |
| `BitBuffer.java` | 4159 | `d5496452b435423beead30aa356e10a7c0ba4790b7da37ee4a1b80b4df136447` |
| `DataTooLongException.java` | 2890 | `7661186dde4b27334fd94f4950f58522eaab256274388152e5cb8e35ef463e1a` |
| `README-upstream.markdown` (license/usage text) | 4032 | `eea862d8e975c6df197b050e5bd6c93b70c046952ac704b4ee1d213f2393f52a` |

Used only by `org.kiosk.harness.pairing.QrCodeView` to render the locally generated pairing QR.
The app never encodes QR content anywhere else and never sends it to a third party; the payload is
the trusted origin plus the 8-character user code (see `PairingPayload`).
