# Arena Controller

Arduino Mega sketch that runs a combat robotics match: ready buttons, countdown, match timer, pause (unstick), tapout, LED strip, and sound cues. Everything can also be driven from the Serial Monitor.

## Upload

1. Arduino IDE: install the **Adafruit NeoPixel** library (Library Manager).
2. Board: **Arduino Mega or Mega 2560**. Open `Arena_controller_FSM.ino` and upload.
3. Serial Monitor at **9600 baud**. Any line-ending setting works.

## Serial keys (case sensitive)

| Key | Does |
|---|---|
| `f` | Start the match (skips the ready buttons), or unpause |
| `u` | Pause (unstick) |
| space | End the match (also cancels a countdown) |
| `r` | Reset after a match |

## States

The sketch prints `state: N` whenever the state changes, and `time: N` once a second during a fight.

| N | State | Lights |
|---|---|---|
| 0 | Idle, waiting for both teams to press ready | White; each team's half lights up when they ready |
| 4 | Countdown | 3 red flashes |
| 1 | Fight (timer running) | Blue for 2 s at FIGHT, then white |
| 2 | Paused (unstick) | Yellow |
| 3 | Match over | Red until reset |

## Pins (Mega)

| Pins | Use |
|---|---|
| 9 | LED strip data (197 pixels: 97 team 1, 100 team 2) |
| 3-8 | Sound triggers, active LOW: team 1 ready, team 2 ready, fight, 1 minute, 30 seconds, fight end |
| 22 / 24 | Team 1 / team 2 green (ready, then unstick during a fight) |
| 26 / 28 | Team 1 / team 2 red (tapout) |
| 23, 25, 27, 29 | Driven LOW as ground for the team buttons |
| 33 / 35 / 37 | Controller start / pause / stop |
| 36 | Controller reset |
| 32 / 34 | Controller timer add / subtract (wired, not used by the code yet) |

Buttons connect the pin to ground (internal pull-ups). Match length is `match_length_millis` (3 minutes).
