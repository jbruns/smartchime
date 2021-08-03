# smartchime
## a doorbell, written in Python

**..wait, a doorbell in Python?**
why, yes, yes indeed! Why, you ask? Well, two problems presented themselves at once:
- I had a hole in my wall, thanks to a very old, very tired NuTone intercom head flush-mounted right next to my front door. I am exceedingly grateful for its many years of service (never a missed Winchester chime since I moved in and presumably, dating all the way back to when the house was built in 1967). It even played along for a few years wired up to a doorbell camera. 

- I needed to learn and practice some more practical(-ish) Python. As a bonus, this particular project presented an opportunity to integrate simpler hardware devices, and interact with them at a slightly lower level - with the ultimate goal being to create a cohesive, useful thing out of several distinct components.

## Highlights

**It's a doorbell:** feed it any sound file, and it'll happily play when someone's at the door. 

**Event-based triggers:** support is written in for motion, doorbell press, and rotary encoders/switches providing various functions. Event delivery is expected via an MQTT broker, so the chime integrates very well with Home Assistant.

**Toddler-resistant:** my son thought the doorbell was quite impressive, and soon wanted to find out just how many times he could cause it to play a sound per second. The device of course complied with his stress test, but it shined light on the fact that I should probably rate-limit the chime.

**Customizeable messages:** A small OLED display is always on and able to display various widgets, including a scrolling message string delivered via MQTT. This way, any data available to Home Assistant (temperatures, sensors, calendar events, holidays, birthdays, mail delivery, you name it!) is something that can be displayed.

**Spotify, MPD, Airplay, or Bluetooth target:** all the capabilities of a smart speaker are here, so they're enabled.