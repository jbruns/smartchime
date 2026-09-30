# Home Assistant owns Panel sleep

The Panel's on/off behaviour is decided solely by Home Assistant's Panel Mode: Sleep renders a pure-black screen (on AMOLED, black pixels are off), and the Pi performs no display power management of its own. Previously both HA's Sleep mode and an X11 DPMS timeout on the Pi could blank the Panel, and only Doorbell Events woke DPMS, so the Panel could be dark during Motion or Alert. One owner makes Panel state predictable and keeps touch-to-wake (via browser_mod) working.

## Considered Options

- **Pi DPMS owns sleep, HA drops Sleep mode**: rejected; the Pi only hears Doorbell Events, so it cannot wake for Motion, Critical Alert, or the Display Schedule.
- **Keep both**: rejected; the two timers race and produce a dark Panel in modes that should be visible.
