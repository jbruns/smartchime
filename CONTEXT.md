# Smartchime

A smart doorbell chime for the entryway: it plays chimes, drives a small status OLED, and hosts a touchscreen panel, with Home Assistant deciding what each shows.

## Language

### Events and displays

**Doorbell Press**:
A visitor pressing the front door doorbell button.
_Avoid_: Ring, visitor event

**Doorbell Event**:
The message Home Assistant sends Smartchime reporting that a Doorbell Press started or ended; an active one plays the Chime.
_Avoid_: ring event, doorbell message

**Chime**:
The sound Smartchime plays for an active Doorbell Event.
_Avoid_: ringtone, alert sound

**OLED State**:
A complete snapshot of what the status OLED should show, republished whenever any of its inputs change.
_Avoid_: OLED message, OLED update

**Panel**:
The wall-mounted AMOLED touchscreen showing the Smartchime dashboard.
_Avoid_: AMOLED dashboard, kiosk, HDMI display

**Panel Mode**:
Which screen the Panel is showing: Sleep, Idle, Visitor, Person, Hazard, or Controls. Exactly one at a time.
_Avoid_: AMOLED mode, dashboard state

### Status

**Hazard**:
A single on/off condition that is on while any sensor reports a dangerous condition (smoke, CO, water leak); it takes over the Panel.
_Avoid_: Critical Alert, Alert, alarm, emergency

**Acknowledge**:
Dismissing a Hazard from the Panel; it stays dismissed until the Hazard clears.
_Avoid_: clear, silence

**Open Doors**:
The doors currently open, shown live on Idle; never a takeover and never timed.
_Avoid_: door ajar, door alert, door open too long

### Schedule

**Display Schedule**:
The four daily Periods (Morning, Day, Evening, Night) shared by the OLED and the Panel.
_Avoid_: OLED schedule, night mode

**Period**:
One slice of the Display Schedule; Night turns the OLED off and puts the Panel to Sleep, the others set OLED contrast.
_Avoid_: time of day, phase
