# Arena Controller: session notes

Club repo (railsiderobotics/arena-controller). Also has a remote `raspi-code` branch not touched here.

## Status
- 2026-11-17: bug fixes on `fix/fsm-bugfixes` (non-blocking FSM, timer fixes, see `FIX_REPORT.md`). Compiles for Mega; NOT run on hardware yet.
- Feature branches: `feature/clear-ready-lights` (built on the fix branch), `feature/wokwi-simulator` (built on main, independent).

## Next steps
- Run the hardware checklist in `FIX_REPORT.md` (stopwatch the 3:00 match), or the same steps in the Wokwi simulator.
- Decide timer add/subtract button behavior (pins 32/34 unused).
- Later: connect to bracket-app over serial.

## Decisions & gotchas
- Branching: one branch per change type. `fix/...` for bug fixes, `feature/...` for each new feature, each its own pull request. A feature that needs the fixes is built on the fix branch: merge the fix PR first, then the feature PR shows only its own commits.
- Compile check: Arduino IDE's bundled `arduino-cli` (`C:/Program Files/Arduino IDE/resources/app/lib/backend/resources/arduino-cli.exe`), FQBN `arduino:avr:mega`. Needs the Adafruit NeoPixel library (or a stub header passed with `--libraries`).
- Never call `pixels.show()` every loop: 197 px disables interrupts ~6 ms and `millis()` loses time.
- States: 0 idle, 1 fight, 2 paused, 3 over, 4 countdown.

## Log
- 2026-11-17: FSM rework (receivedChar bug, slow timer, countdown counted as match time, blocking delays, serial flood).
