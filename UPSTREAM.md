# Upstream provenance

## macOS

- Source: <https://github.com/HD838A/remote-mic-app>
- Imported tag: `v1.2.3`
- Imported commit: `32edebde6a221c84b921a13a61f8cbdceb41c686`
- License: `GPL-3.0-only`
- Excluded during import:
  - `Resources/AppIcon.png`
  - `Resources/AppIcon.icns`
  - `Resources/RC003-remote-photo.png`
  - `Resources/xiaohongshu-cover-v3.png`
  - `Screenshots/`

The excluded assets are not required for the protocol or platform
implementation. `Resources/AppIcon.png` and `Resources/AppIcon.icns` in this
repository are newly generated MiVibe Remote assets, not copies of the
upstream logo.

## Windows

- Source: <https://github.com/xxb26553663-star/remote-bridge-hub>
- Imported tag: `v1.0.0`
- Reference/import commit: `8a93f321ac71a602300c6cd77f7256fa4b63068e`
- License: `GPL-3.0`

The Windows repository is the upstream explicitly credited by the macOS
project. The Xiaomi standalone application already contains WinRT ATVV,
Windows input injection, VB-CABLE routing, packaging, and tests.

## Protocol reference

- Source: <https://github.com/VincentKingHsu/MiRemoteVoice>
- Reviewed tag: `v1.0.0-beta.2`
- Reviewed commit: `2c374d9d65ed6c8b1af6a4f9aa1b6c0f8a039aaf`
- App license: MIT
- Driver license: GPL-3.0

MiRemoteVoice is reviewed as a smaller independent implementation and is not
vendored wholesale into this repository. Its MIT-licensed `AudioPipe.swift`
design informs the MacBook-microphone passthrough and remote-wins source
selection used by the macOS application.
