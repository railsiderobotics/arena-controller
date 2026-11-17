# Arena Controller: Bug Fix Report (2026-11-17)

`Arena_controller_FSM.ino` was reworked to fix the bugs below. Pins, serial keys, colors, sounds, sound hold times, match length, and the countdown timing are the same unless listed under "Behavior changes".

**Verification:** compiled for the Arduino Mega with `arduino-cli` (AVR core 1.8.6, all warnings on): no warnings from the sketch. The Adafruit NeoPixel library isn't installed on this PC, so it was compiled against a stub with the same function signatures. **Not run on the hardware.** Use the checklist at the end before an event.

## Bugs fixed

**1. `receivedChar = "o";` stored a memory address in a `char`.** `"o"` is a string, not the character `'o'`, so this put the low byte of the string's address into `receivedChar` after every loop (the compiler warns about it). Today that byte happens not to be `f`, `u`, `r` or space, but any change to the sketch can move the string, and if it lands on one of those, that command fires every single loop (e.g. every match ends instantly).
*Fix:* `receivedChar` is cleared to `0` at the start of each loop.

**2. The match timer ran slow.** Every loop in the fight state redrew all 197 LEDs (`color_fill(255,255,255)`), and every loop printed the state and timer at 9600 baud. `pixels.show()` turns interrupts off for about 6 ms on 197 pixels, and `millis()` misses most of its ticks while they're off. My estimate is that `millis()`, and so the match timer, ran at roughly 60-65% speed, so a 3:00 match lasted about 4½-5 minutes of real time (worth timing the old code against a stopwatch to confirm). The "1 minute left" and "30 seconds left" calls were late by the same factor.
*Fix:* LEDs are only redrawn when something changes, and the serial output is cut down (see 7).

**3. The countdown counted as match time on a fresh start.** The 0→1 transition set the timer's start point *before* the ~11 s countdown, so that time came out of the match. (The unpause path already did it right.)
*Fix:* the timer starts at FIGHT in both paths.

**4. A finished match could keep processing in the same loop.** After time ran out or a tapout set `state = 3`, the rest of the fight checks still ran: a green button held at that moment flipped the finished match to "paused", and a tapout right at time-up played the end sequence twice.
*Fix:* every transition `break`s out of the state.

**5. Missing braces in the match-over state.** Line 310 read `if (reset) state = 0; color_fill(255,255,255);`, so the white fill ran every loop (part of bug 2), and the lights went white 5 s after every match instead of staying red until reset.
*Fix:* braces added. Lights stay red until reset, then go white.

**6. Buttons were ignored while sounds played and during the countdown.** `delay()` blocked the loop: 3 s for each warning sound (a tapout pressed during the "1 minute left" call was missed unless held), about 7-9 s of countdown where Stop did nothing, and 5 s after a match ended.
*Fix:* no `delay()` is left in `loop()`. The countdown is now its own state (state 4, Stop cancels it), and sounds go into a small queue: each still holds its pin LOW for the same time and they still play one after another, but the loop keeps reading buttons meanwhile.

**7. The serial output was flooded.** The state number printed every loop (thousands of lines a second), which made the Serial Monitor unreadable and, at 9600 baud, slowed the loop down.
*Fix:* prints `state: N` only when the state changes and `time: N` once a second during a fight. Event messages are unchanged. This also makes the output easy to read from the bracket app later.

**8. The ESP setting didn't work.** `ESP = true` only flipped which level counts as "pressed"; the pins still used `INPUT_PULLUP`, so every button would read as pressed.
*Fix:* replaced with `BUTTON_MODE` and `BUTTON_PRESSED` at the top, plus a comment on what to change for an ESP32 (pin numbers too: most of 22-37 don't exist there).

**Small fixes:** the button "ground" pins are now driven LOW explicitly instead of relying on the power-on default; Serial Monitor line endings (`\n`, `\r`) are ignored instead of echoed as commands; "fight paused", "tapout", etc. now end with a newline so messages don't run together; the comment said the pause color was purple but the code sets yellow (comment fixed, color kept); timer variables are `unsigned long` like `millis()`; the typo `match_lenght_millis` is now `match_length_millis`; unused variables (`DELAYVAL`, `red`, `green`, `blue`) removed.

**Docs:** new `README.md` with upload steps, serial keys, states, and the pin map.

## Behavior changes to know about

- **FIGHT:** the blue light now comes on together with the FIGHT sound and the timer. Before, the strip went dark for 2 s after the third red flash (while the sound played), then blue for 2 s, then white.
- **Stop during the countdown** ends the match (state 3, red) instead of being ignored.
- **After a match,** the lights stay red until reset (bug 5).
- **Ready sounds overlap the countdown.** Before, both ready sounds finished (up to 6 s) before the countdown even began. Now the countdown starts as soon as both teams are ready, and the sounds play during its 2 s lead-in and first flashes. The FIGHT sound still waits for anything queued ahead of it.

## Not changed (worth a decision)

- **A ready press can't be undone.** If one team readies and the match is then delayed or swapped, the next opponent's ready press starts the match instantly. Fixed separately on branch `feature/clear-ready-lights` (reset before a match clears the ready lights).

- **Timer add/subtract buttons (pins 32, 34)** are wired and set up as inputs but the code never reads them. Needs a decision on how much time each press adds or removes.
- **LED power:** brightness 255 with all 197 pixels white draws up to about 12 A. If the supply is smaller, lower `LED_BRIGHTNESS`.
- **Colors:** team 1 ready shows red and team 2 ready shows green, while the bracket app calls team 1 red and team 2 blue. Worth matching once the two systems are connected.

## Hardware test checklist

1. Power on: white, Serial Monitor shows `<Arduino is ready>` and `state: 0`.
2. Team 1 green, then team 2 green: each half lights, each ready sound plays, countdown starts (`state: 4`), 3 red flashes, FIGHT sound + blue, white after 2 s (`state: 1`).
3. Time a full match with a stopwatch: should end at 3:00, with the 1-minute and 30-second calls at 2:00 and 2:30.
4. During a fight press green: yellow + sound (`state: 2`). Press start: 3 red flashes, FIGHT, timer continues where it stopped.
5. Press a red button right as the 1-minute call plays: the match should end immediately.
6. Press Stop during a countdown: red, `state: 3`. Reset: white, `state: 0`.
7. Type `f`, `u`, space, `r` in the Serial Monitor with "Newline" line endings: each works once and the newline is ignored.
