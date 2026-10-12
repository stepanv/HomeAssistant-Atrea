# Fork maintenance

This fork builds on JurajNyiri/HomeAssistant-Atrea and offers generic native
Home Assistant entities. Room names, CO2 calibration, and household automations
belong in the user's Home Assistant configuration.

## Upstream contributions

| Change | Upstream PR |
| --- | --- |
| Options without saved presets | https://github.com/JurajNyiri/HomeAssistant-Atrea/pull/37 |
| Off and Auto command dispatch | https://github.com/JurajNyiri/HomeAssistant-Atrea/pull/38 |
| Discrete ventilation/circulation controls | https://github.com/JurajNyiri/HomeAssistant-Atrea/pull/39 |
| Native status and optional diagnostic entities | https://github.com/JurajNyiri/HomeAssistant-Atrea/pull/40 |
| Remove invalid climate state unit | https://github.com/JurajNyiri/HomeAssistant-Atrea/pull/42 |
| Legacy temperature fallback | https://github.com/JurajNyiri/HomeAssistant-Atrea/pull/41 |
| Library runtime dependency | https://github.com/JurajNyiri/pyatrea/pull/8 |
| Library discrete-power API | https://github.com/JurajNyiri/pyatrea/pull/9 |

All upstream contributions remain drafts pending review. The discrete-control
PR additionally requires its pyatrea API to be released upstream.
The fork pins an immutable library source archive, including its dependency fix.
No PyPI package has been published by this fork.

## Installing the fork

Add `https://github.com/stepanv/HomeAssistant-Atrea` as a custom integration
repository in HACS. Select an explicitly tested revision. The current review branch is
`review/combined-2026-10-10`; no fork release has been published. The integration
domain remains `atrea`; retain the existing config entry and device.

Do not allow two HACS repositories to manage the same `custom_components/atrea`
directory. Switch the repository in HACS as part of installation and restart
Home Assistant after the files and library requirement have been updated.

This fork exposes generic native entities. Private attributes from locally
modified versions are not part of its API. Migrate templates and automations
that depend on such attributes before switching. Enable any needed diagnostic
entities from the device page; diagnostic entities are disabled by default.

## Development and releases

- Keep bug fixes and features on separate branches based on upstream `master`.
- Merge accepted local work into fork `master`; preserve upstream ancestry.
- Run `python -m pytest tests -q` with the manifest's pyatrea requirement installed.
- Current validation target: Home Assistant 2026.9.0 on Python 3.14.
- Use prereleases until installation and behavior have been verified on hardware.
- Returning to upstream is optional. Require released equivalents for every
  needed feature before removing the fork requirement.

## Known follow-up work

- Replace remaining climate attributes with native equivalents where needed;
  retain existing public upstream attributes during migration.
- Determine unit-specific fan/actuator and bypass semantics from device metadata
  before presenting raw codes as user-facing units or writable controls.
- Add translation keys for new entity names and enum options.
- Review shared command-queue handling and polling failure recovery separately.
