# Retained D1–D4 activity

On controllers exposing `config/log.cgi`, the integration checks the retained
H10712 (forced operating source) log every 30 seconds. This can recover short
input-triggered activity missed by normal status polling. It only reads data;
input binary sensors continue to show the actual status registers.

## What appears in Activity

An entry is attached to the corresponding D1–D4 entity and uses its current HA
name, for example:

> D1 input became the forced operating source at 2026-10-21 08:05:00
> (controller local time)

The Activity entry itself has the discovery time. The message preserves the unit's
time, without backdating the HA event: HA's live Activity stream can discard
backdated events. No synthetic input on/off states are generated.

## Recovery and limitations

- The first run imports the most recent ten minutes of today's log.
- A persistent cursor prevents normal poll/restart duplicates. The earlier
  experimental seconds-only cursor is migrated without replaying old entries.
- After downtime, available retained days are recovered chronologically, up to
  three days per poll. Days already expired on the controller cannot be recovered.
- The midnight baseline and repeated unchanged values are not activations.
- Same-second transitions and clock changes retain the controller's row order.
  The reported time is explicitly controller-local; HA and controller clocks
  should agree. An ambiguous autumn clock-change time is not assigned a guessed
  UTC offset.
- H10712 identifies the forced source, not every physical contact edge. Repeated
  presses while the source remains D1, or inputs masked by another priority,
  cannot be inferred. A source resuming after a higher priority is activity,
  not proof of a new press. Normal input state-change entries may also appear.
- Network/authentication/unsupported-log errors leave normal integration polling
  unaffected and retry later without advancing the cursor. A truncated or
  rewritten log before the saved position is not replayed; it emits a warning.
- Event recording and cursor storage are separate operations: a crash between
  them can duplicate the last batch. This is not an exactly-once event journal.

Verified with an R-5 RK5 retained-log format. Other controllers may not expose
this endpoint; no calibration, household names, or firmware assumptions are added.

## Review journey

Trigger an input, allow a poll, and open the device's Activity tab. Capture the
entry showing the input name, discovery time and controller time. Leave the view
open for another activation to check live appearance. Reload the integration:
the already consumed entries should not be emitted again. The climate preset
and physical input states are not changed by this reader.
