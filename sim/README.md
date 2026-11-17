# Testing without the arena

Three ways to test, from least to most hardware:

## 1. Wokwi simulator (no hardware at all)

[Wokwi](https://wokwi.com) runs the real sketch on a simulated Arduino Mega in the browser. It's free, and you don't need an account to run a project.

`diagram.json` wires up a Mega with:
- a 197-pixel ring standing in for the LED strip (first 97 pixels = team 1, the rest = team 2),
- the 8 buttons (team greens and reds, controller start / pause / stop / reset), wired to the same pins as the arena,
- 6 orange LEDs, one per sound trigger pin (3-8). An LED is lit while that sound's pin is held LOW, i.e. while the sound would play.

Setup (about 2 minutes):
1. Go to https://wokwi.com/projects/new/arduino-mega.
2. In the `sketch.ino` tab, replace everything with `Arena_controller_FSM.ino` from this repo (whichever branch you want to test).
3. In the `diagram.json` tab, replace everything with `sim/diagram.json`.
4. Open the **Library Manager** tab, press **+**, and add **Adafruit NeoPixel** (or create a `libraries.txt` with the contents of `sim/libraries.txt`).
5. Press the green Play button.

Using it:
- Click the buttons, or click the simulation area once and use the keyboard shortcuts shown on each button's label: `1` / `2` team ready, `Q` / `W` team tapout, `S` start, `P` pause, `X` stop, `R` reset.
- Type the serial keys (`f`, `u`, space, `r`) into the Serial Monitor at the bottom. It also shows the `state:` and `time:` messages.
- To test the timer faster, temporarily change `match_length_millis` (e.g. to `40UL * 1000UL`). The 1-minute call then fires right away and the 30-second call at 10 s.

Saving the project to your Wokwi account is optional and makes it a Wokwi project you can reopen; it isn't needed to run it.

Limits: there's no sound board, so sounds are just the LEDs. Wokwi runs close to real time, but use a real board for the final stopwatch check of the 3:00 match.

## 2. A bare Arduino Mega over USB

Upload the sketch to any Mega with nothing attached and use the Serial Monitor (9600 baud). `f` starts a match, `u` pauses, space ends it, `r` resets, and you can follow the `state:` / `time:` messages. You can also jumper a button pin (e.g. 26, team 1 red) to GND with a wire to fake a button press.

## 3. The full arena

Use the hardware checklist in `FIX_REPORT.md` (on the `fix/fsm-bugfixes` branch).
