# Faults and warnings

Three read-only problem sensors are created when supported by the unit:

- **Fault active**: any active controller alert.
- **Warning active**: any active controller warning.
- **Filter maintenance required**: filter-clogging or filter-replacement-interval
  warning, when declared by the unit. This remains part of the warning summary.

Their attributes list all active descriptions and register codes. Text comes
from the controller's already-loaded translations; an untranslated condition
falls back to `Fault (code)` or `Warning (code)`. Warning classification follows
controller metadata, which can include operating notices such as defrosting.

The first active condition and final clearance use normal HA on/off Activity
entries. If conditions change while a summary remains on, one additional entry
lists the new and cleared descriptions. Unchanged polls produce no new entries.
Startup and reconnection do not invent cleared or newly activated conditions.

A failed status poll makes the sensors unavailable. Missing/invalid flags cannot
produce an all-clear state. A known active flag still reports a problem even if
other flags are missing; `unavailable_codes` lists the incomplete readings.

The sensors do not reset faults, acknowledge warnings, create notifications or
send commands. Existing acknowledgement buttons are separate. Automations can
use these sensors to notify on a new problem or on a maintenance reminder.
