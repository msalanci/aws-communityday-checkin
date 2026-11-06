<!-- Copyright (c) 2026-2027 Michal Salanci. SPDX-License-Identifier: MIT -->

# vendor/

Third-party files the scanner page loads from its own origin, so the page needs no CDN.

| File | What it is |
|---|---|
| `html5-qrcode.min.js` | [html5-qrcode](https://github.com/mebjas/html5-qrcode) 2.3.8, the browser build from the npm package, unchanged |
| `html5-qrcode.LICENSE` | Its licence, Apache-2.0, from the same package |

## Where it came from

- npm tarball: `https://registry.npmjs.org/html5-qrcode/-/html5-qrcode-2.3.8.tgz`
- npm's published integrity (`dist.integrity` of 2.3.8): `sha512-jsr4vafJhwoLVEDW3n1KvPnCCXWaQfRng0/EEYk1vNcQGcG/htAdhJX0be8YyqMoSz7+hZvOZSTAepsabiuhiQ==`; the downloaded tarball matched it.
- SHA-256 of `html5-qrcode.min.js` as copied: `660b12437b1d747e3e68b8be0685c08cb728140110ad213f167b14b66f8b1d8e`

To check it again:

```bash
curl -s https://registry.npmjs.org/html5-qrcode/-/html5-qrcode-2.3.8.tgz -o html5-qrcode-2.3.8.tgz
echo "sha512-$(openssl dgst -sha512 -binary html5-qrcode-2.3.8.tgz | openssl base64 -A)"
tar -xzf html5-qrcode-2.3.8.tgz package/html5-qrcode.min.js
shasum -a 256 package/html5-qrcode.min.js
```
