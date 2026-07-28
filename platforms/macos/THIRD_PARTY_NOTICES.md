# Third-party notices

## remote-mic-app

- Project: `HD838A/remote-mic-app`
- Source: <https://github.com/HD838A/remote-mic-app>
- Imported revision: `v1.2.3` / `32edebde6a221c84b921a13a61f8cbdceb41c686`
- License: GNU General Public License v3.0 only (`GPL-3.0-only`)

MiVibe Remote for macOS is a modified version of this project and directly reuses its CoreBluetooth, ATVV, IOHID, CoreAudio, settings, test and packaging implementations. The upstream proprietary Logo, product photo and screenshots are excluded.

## remote-bridge-hub

- Project: `xxb26553663-star/remote-bridge-hub`
- Source: <https://github.com/xxb26553663-star/remote-bridge-hub>
- Reference revision: `8a93f321ac71a602300c6cd77f7256fa4b63068e`
- License: GNU General Public License v3.0 only (`GPL-3.0-only`)

The Xiaomi RC003 ATVV UUIDs, microphone command behavior, IMA/DVI ADPCM decoding order, capability parsing, and HID usage mapping were adapted from this project. The macOS implementation uses Apple public frameworks and does not include the upstream Windows injection, VB-CABLE packaging, commercial branding, or customer systems.

## BlackHole

- Project: `ExistentialAudio/BlackHole`
- Source: <https://github.com/ExistentialAudio/BlackHole>
- Pinned source revision: `v0.7.1` / `e2b22aaaba4e507a097131704bf96dabc004d9cf`
- License: GNU General Public License v3.0 (`GPL-3.0`)

BlackHole remains an optional loopback-device choice. This fork includes `scripts/build-doubao-driver.sh` and `third_party/blackhole/blackhole-device-usb.patch`, which build a distinct `MiRemoteV2ch.driver` from the pinned BlackHole source. The patch changes only the actual Audio Device transport type to USB and assigns a separate CFPlugIn factory UUID; it does not modify an installed `BlackHole2ch.driver`. The release build embeds the derived driver in a dedicated macOS Installer package. End users install that package from the DMG and do not need the source build tools.

## MiRemoteVoice

- Project: `VincentKingHsu/MiRemoteVoice`
- Source: <https://github.com/VincentKingHsu/MiRemoteVoice>
- Reference release: `v1.0.0-beta.2`
- Application license: MIT

The Doubao compatibility design is informed by MiRemoteVoice: a side-by-side BlackHole-derived device reports its actual audio Device as USB transport so Doubao can enumerate it. This fork reimplements that idea as a pinned, source-built BlackHole patch instead of reusing MiRemoteVoice's version-specific binary replacement script.

## Product imagery

No Xiaomi product photo, upstream screenshot or upstream proprietary App Logo is bundled. The settings interface uses a code-drawn remote silhouette and a newly generated MiVibe icon, so the build does not depend on unclear product-image redistribution rights.
