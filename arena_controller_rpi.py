#!/usr/bin/env python3
# sudo /home/railside/arena_controller/arena_env/bin/python3 "%f"

import json
import logging
import time
import threading
import RPi.GPIO as GPIO
import pygame
import board
import neopixel
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

# ==================== SCREEN CONFIGURATION ====================

SCREEN_WIDTH  = 1000
SCREEN_HEIGHT = 550

# ==================== CONFIGURATION ====================

MATCH_LENGTH_SECONDS = 120  # beetle (2 min)
ANT_LENGTH_SECONDS   = 120  # ant (2 min)

# GPIO pin numbers (BCM)
RED_GREEN        = 2
BLUE_GREEN       = 3
RED_RED          = 4
BLUE_RED         = 5
RED_YELLOW       = 6
BLUE_YELLOW      = 7
CONTROLLER_START = 8
CONTROLLER_RESET = 9
WHITE_LIGHT      = 10   # separate white light strip, 3.3V output, HIGH = on

# ==================== RGB LED STRIP (NeoPixel) ====================

LED_PIN          = board.D18       # GPIO18 (PWM)
RED_ZONE_COUNT   = 97             # pixels in the red team zone
BLUE_ZONE_COUNT  = 100            # pixels in the blue team zone (197 total)
LED_BRIGHTNESS   = 0.4            # 0.0 - 1.0
LED_ORDER        = "BRG"          # string order

LED_COUNT = RED_ZONE_COUNT + BLUE_ZONE_COUNT
RED_ZONE  = range(0, RED_ZONE_COUNT)
BLUE_ZONE = range(RED_ZONE_COUNT, LED_COUNT)

LED_REFRESH_S = 0.2
DEBOUNCE_S = 0.2

READY_HOLD_S = 2.0
READY_TO_START_DELAY_S = 1.5

START_RED_S         = 3.0   # 3, 2, 1 countdown: one red flash per second
START_FLASH_ON_S    = 0.5   # each red flash is on this long, then off for the rest of that second
START_GREEN_MATCH_S = 1.5   # Green phase for the first 1.5 seconds of the match
END_RED_S           = 3.0   # after a match ends (tapout / end / time over): red this long, then white

# ---- Web / network ----
WEB_COMMAND_TTL_S  = 2.0    # a web command the controller didn't pick up in this long is dropped,
                            # so stale commands can't fire later (e.g. a double-clicked Start)
STATUS_POLL_S      = 0.05   # how often the publisher checks for a state change
STATUS_HEARTBEAT_S = 2.0    # push a status event at least this often so pages can tell the link is alive

COLOR_NAMES = {
    (True,  True,  True):  'white',
    (True,  False, False): 'red',
    (False, True,  False): 'green',
    (False, False, True):  'blue',
    (True,  True,  False): 'yellow',
    (False, True,  True):  'cyan',
    (True,  False, True):  'magenta',
    (False, False, False): 'white',
}

# All timing uses the monotonic clock: it can't jump if the Pi's clock gets
# corrected over the network in the middle of a match.
now_s = time.monotonic

# ==================== SCREEN DISPLAY ====================

class ScreenDisplay:
    STATE_LABELS = {
        0: ((128, 128, 128), "WAITING FOR TEAMS"),
        1: ((0,   0,   255), "MATCH IN PROGRESS"),
        2: ((255, 255,   0), "PAUSED"),
        3: ((255,   0,   0), "MATCH COMPLETE"),
    }

    def __init__(self):
        self._last_key  = None   # (seconds shown, state) of the last frame drawn
        self._last_draw = 0.0
        try:
            pygame.display.init()
            pygame.font.init()
            self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
            pygame.display.set_caption("Arena Controller - Timer")

            self.font_huge   = pygame.font.Font(None, 500)
            self.font_medium = pygame.font.Font(None, 40)
            self.enabled = True
            print("Screen display initialized")
        except Exception as e:
            print(f"Screen display init error: {e}")
            self.enabled = False

    def draw(self, elapsed_ms, total_ms, state):
        if not self.enabled:
            return
        try:
            pygame.event.pump()   # keep the window responsive to the desktop

            remaining = max(0, total_ms - elapsed_ms)
            secs = int(remaining / 1000)

            # Only redraw when the picture would actually change (once a second
            # or on a state change). Rendering the huge font 50x/sec was a big
            # CPU load on the Pi. A redraw every second also repairs the window
            # if it was covered.
            key = (secs, state)
            now = now_s()
            if key == self._last_key and now - self._last_draw < 1.0:
                return
            self._last_key  = key
            self._last_draw = now

            self.screen.fill((0, 0, 0))

            time_str = f"{secs // 60:02d}:{secs % 60:02d}"
            timer_surf = self.font_huge.render(time_str, True, (255, 255, 255))
            self.screen.blit(timer_surf, timer_surf.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 3)))

            color, label = self.STATE_LABELS.get(state, ((255, 255, 255), "UNKNOWN"))
            label_surf = self.font_medium.render(label, True, color)
            self.screen.blit(label_surf, label_surf.get_rect(center=(SCREEN_WIDTH // 2, int(SCREEN_HEIGHT / 1.5))))

            pygame.display.flip()
        except Exception as e:
            print(f"Draw error: {e}")

    def close(self):
        if self.enabled:
            try:
                pygame.quit()
            except Exception:
                pass


# ==================== ARENA CONTROLLER ====================

class ArenaController:

    def __init__(self):
        self.web_command       = None
        self.web_command_value = None
        self.web_command_time  = 0.0     # when the current web command arrived
        self.state             = 0
        self.ready1            = False
        self.ready2            = False
        self.timer_start       = 0.0
        self.timer_elapsed_ms  = 0
        self.match_length_ms   = MATCH_LENGTH_SECONDS * 1000
        self.weight_class      = None
        self.min_warned        = False
        self.halfmin_warned    = False
        self._last_press       = {}
        self.team1_name        = ""
        self.team2_name        = ""
        self.teams_set         = False
        self.white_on          = False
        self.manual_white      = None  # Explicit manual override flag (True, False, or None)
        self._led_gen          = 0

        self.ready_hold_until  = 0.0
        self.start_at          = 0.0
        self.end_red_until     = 0.0   # match-complete lights stay red until this time, then white

        self.timer_color         = 'white'
        self.start_sequence      = False
        self.start_countdown_sec = 0
        self.red_ready_shown     = False
        self.blue_ready_shown    = False
        self.waiting_for_ready   = False

        self.web_presses = {}
        self.PIN_NAMES = {
            RED_GREEN:  'red_green',  RED_YELLOW:  'red_yellow',  RED_RED:  'red_red',
            BLUE_GREEN: 'blue_green', BLUE_YELLOW: 'blue_yellow', BLUE_RED: 'blue_red',
        }

        self.screen = ScreenDisplay()

        self._led_lock   = threading.Lock()
        self._last_fill  = None
        self._last_show  = 0.0
        self._strip_white = None
        self.pixels = neopixel.NeoPixel(
            LED_PIN, LED_COUNT,
            brightness=LED_BRIGHTNESS,
            auto_write=False,
            pixel_order=LED_ORDER,
        )

        self._setup_gpio()
        self._all_white()
        print(f"Arena Controller Initialized ({RED_ZONE_COUNT} red + {BLUE_ZONE_COUNT} blue pixels)")

    def _setup_gpio(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        inputs = [
            RED_GREEN,   BLUE_GREEN,
            RED_RED,     BLUE_RED,
            RED_YELLOW,  BLUE_YELLOW,
            CONTROLLER_START, CONTROLLER_RESET,
        ]
        for pin in inputs:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        GPIO.setup(WHITE_LIGHT, GPIO.OUT, initial=GPIO.LOW)

    def _pressed(self, pin):
        name = self.PIN_NAMES.get(pin)
        if name:
            t = self.web_presses.pop(name, None)
            if t is not None and now_s() - t < 1.0:
                return True

        if GPIO.input(pin) != GPIO.LOW:
            return False
        now = now_s()
        if now - self._last_press.get(pin, -1e9) < DEBOUNCE_S:
            return False
        self._last_press[pin] = now
        return True

    def _led_fill(self, r, g, b):
        """Fill the whole strip. Skips the write if the strip is already that
        color, but re-sends every LED_REFRESH_S so a glitched pixel heals itself."""
        color = (r, g, b)
        with self._led_lock:
            now = now_s()
            if color != self._last_fill or now - self._last_show >= LED_REFRESH_S:
                self.pixels.fill(color)
                self.pixels.show()
                self._last_fill = color
                self._last_show = now
        self.timer_color = COLOR_NAMES.get((r > 127, g > 127, b > 127), 'white')

        # Evaluate white light state: manual override takes precedence if set, otherwise follow RGB color
        if self.manual_white is not None:
            strip_white = self.manual_white
        else:
            strip_white = (r, g, b) == (255, 255, 255)

        if strip_white != self._strip_white:
            self._strip_white = strip_white
            self.set_white_light(strip_white)

    def _all_white(self):
        """Force everything white (strip + GPIO 10) and clear the manual override.
        Used at startup and on reset. Idle/match code uses _led_fill instead, which
        doesn't rewrite the whole strip 50 times a second."""
        self.manual_white = None
        with self._led_lock:
            self.pixels.fill((255, 255, 255))
            self.pixels.show()
            self._last_fill = (255, 255, 255)
            self._last_show = now_s()
        self.timer_color = 'white'
        self._strip_white = True
        self.set_white_light(True)

    def _led_refresh(self):
        with self._led_lock:
            now = now_s()
            if now - self._last_show >= LED_REFRESH_S:
                self.pixels.show()
                self._last_show = now

    def set_white_light(self, on):
        self.white_on = bool(on)
        GPIO.output(WHITE_LIGHT, GPIO.HIGH if self.white_on else GPIO.LOW)

    def _reset_requested(self):
        # Reset works in every state (waiting, running, paused, complete), and also
        # during the start countdown and green phase, because _wait() checks this too.
        return self.web_command == 'r' or self._pressed(CONTROLLER_RESET)

    def _wait(self, seconds):
        end = now_s() + seconds
        while now_s() < end:
            if self._reset_requested():
                self._reset()
                return False
            time.sleep(0.02)
        return True

    def _wait_and_tick(self, seconds):
        end = now_s() + seconds
        while now_s() < end:
            if self._reset_requested():
                self._reset()
                return False
            self.timer_elapsed_ms = (now_s() - self.timer_start) * 1000
            time.sleep(0.02)
        return True

    def _start_animation(self):
        self.start_sequence = True
        self.manual_white = None
        try:
            # One red flash per countdown second: 3, 2, 1
            for remaining in range(int(START_RED_S), 0, -1):
                self.start_countdown_sec = remaining
                self._led_fill(255, 0, 0)
                if not self._wait(START_FLASH_ON_S):
                    return False
                self._led_fill(0, 0, 0)
                if not self._wait(1.0 - START_FLASH_ON_S):
                    return False
            return True
        finally:
            self.start_sequence = False
            self.start_countdown_sec = 0

    def _enter_match(self):
        self._led_gen += 1
        if not self._start_animation():
            return

        self.manual_white = None
        self._led_fill(0, 255, 0)

        self.timer_start = now_s() - self.timer_elapsed_ms / 1000
        self.state = 1
        print("Match running (Green phase)")

        if not self._wait_and_tick(START_GREEN_MATCH_S):
            return

        if self.state == 1:
            self._all_white()

    def _end_match(self, natural_end=False):
        if not natural_end:
            self.timer_elapsed_ms = min(self.match_length_ms, (now_s() - self.timer_start) * 1000)
        else:
            self.timer_elapsed_ms = self.match_length_ms

        self.state = 3
        self.screen.draw(self.timer_elapsed_ms, self.match_length_ms, self.state)
        self._led_gen += 1

        self.manual_white = None
        self._led_fill(255, 0, 0)
        self.end_red_until = now_s() + END_RED_S
        print(f"Match complete / tapped out - lights red for {END_RED_S:g}s, then white")

    def _set_weight_class(self, cls):
        self.weight_class = cls
        secs = ANT_LENGTH_SECONDS if cls == 'ant' else MATCH_LENGTH_SECONDS
        self.match_length_ms = secs * 1000
        print(f"{cls.capitalize()}weight selected: {secs // 60} min match")

    def _state_0_waiting(self):
        if self.web_command in ('ant', 'beetle'):
            self._set_weight_class(self.web_command)
            self.web_command = None

        now = now_s()

        if self._pressed(RED_GREEN) and not self.ready1:
            self.ready1 = True
            self.red_ready_shown = True
            self.manual_white = None
            self._led_fill(255, 0, 0)
            self.ready_hold_until = now + READY_HOLD_S
            self.waiting_for_ready = False
            print("Red team ready")

        if self._pressed(BLUE_GREEN) and not self.ready2:
            self.ready2 = True
            self.blue_ready_shown = True
            self.manual_white = None
            self._led_fill(0, 0, 255)
            self.ready_hold_until = now + READY_HOLD_S
            self.waiting_for_ready = False
            print("Blue team ready")

        if self.ready_hold_until and now >= self.ready_hold_until:
            self.ready_hold_until = 0.0
            self._led_fill(255, 255, 255)

        if self.ready_hold_until:
            self._led_refresh()
        else:
            self._led_fill(255, 255, 255)   # idle = white (only re-sent every LED_REFRESH_S)

        start_requested = (
            self._pressed(CONTROLLER_START)
            or self.web_command == 's'
        )

        if start_requested:
            if self.ready1 and self.ready2:
                self.web_command = None
                self.ready_hold_until = 0.0
                self.start_at = 0.0
                self.waiting_for_ready = False

                self.timer_elapsed_ms = 0
                self.min_warned = self.halfmin_warned = False
                self._enter_match()
            else:
                print("Cannot start: Both teams must be ready!")
                self.waiting_for_ready = True
                if self.web_command == 's':
                    self.web_command = None

    def _state_1_match(self):
        self._led_fill(255, 255, 255)   # white during the match (only re-sent every LED_REFRESH_S)

        self.timer_elapsed_ms = (now_s() - self.timer_start) * 1000

        if self.timer_elapsed_ms >= self.match_length_ms - 60_000 and not self.min_warned:
            self.min_warned = True
            print("1 minute left")

        if self.timer_elapsed_ms >= self.match_length_ms - 30_000 and not self.halfmin_warned:
            self.halfmin_warned = True
            print("30 seconds left")

        if self.timer_elapsed_ms >= self.match_length_ms:
            print("Time over")
            self._end_match(natural_end=True)
            return

        if self.web_command == 't':
            self.web_command = None
            print("Match ended from web")
            self._end_match(natural_end=False)
            return

        red_y  = self._pressed(RED_YELLOW)
        blue_y = self._pressed(BLUE_YELLOW)
        pause  = False

        if self.web_command == 'u':
            pause = True
            print("Paused by operator")
        elif red_y:
            pause = True
            print("Paused by red team")
        elif blue_y:
            pause = True
            print("Paused by blue team")

        if pause:
            self.web_command = None
            self.timer_elapsed_ms = (now_s() - self.timer_start) * 1000
            self.state = 2
            self.screen.draw(self.timer_elapsed_ms, self.match_length_ms, self.state)
            self.manual_white = None
            self._led_fill(255, 255, 0)
            print("Match paused")
            return

        if self._pressed(RED_RED):
            print("Red team tapout")
            self._end_match(natural_end=False)
            return
        if self._pressed(BLUE_RED):
            print("Blue team tapout")
            self._end_match(natural_end=False)

    def _state_2_paused(self):
        if self.web_command == 'c':
            self._change_time()
            return

        if self.web_command == 't':
            self.web_command = None
            print("Match ended from pause")
            self._end_match(natural_end=False)
            return

        resume = (
            self._pressed(CONTROLLER_START)
            or self.web_command in ('s', 'u')
        )
        if resume:
            self.web_command = None
            self._enter_match()

    def _state_3_complete(self):
        # Red for END_RED_S after the match ends, then white
        if self.manual_white is None and now_s() < self.end_red_until:
            self._led_fill(255, 0, 0)
        else:
            self._led_fill(255, 255, 255)

        if self.web_command == 'c':
            self._change_time()
            return

        resume = self._pressed(CONTROLLER_START) or self.web_command == 's'
        if resume:
            self.web_command = None
            if self.timer_elapsed_ms < self.match_length_ms:
                print("End match overridden - resuming")
                self._enter_match()
            else:
                print("No time left - add time first")

    def _change_time(self):
        try:
            seconds = int(self.web_command_value)
            self.timer_elapsed_ms = max(0, self.timer_elapsed_ms - seconds * 1000)
            remaining = self.match_length_ms - self.timer_elapsed_ms
            self.min_warned     = remaining <= 60_000
            self.halfmin_warned = remaining <= 30_000
            if seconds > 0:
                print(f"Added {seconds} seconds")
            elif seconds < 0:
                print(f"Subtracted {abs(seconds)} seconds")
        except (TypeError, ValueError):
            print("Invalid time value")
        self.web_command = None
        self.web_command_value = None

    def _reset(self):
        self.team1_name = ""
        self.team2_name = ""
        self.teams_set  = False

        self._led_gen += 1
        self.web_command = None
        self.web_command_value = None
        self.web_presses.clear()
        self.state = 0
        self.ready1 = self.ready2 = False
        self.red_ready_shown = self.blue_ready_shown = False
        self.ready_hold_until = 0.0
        self.start_at = 0.0
        self.end_red_until = 0.0
        self.start_sequence = False
        self.start_countdown_sec = 0
        self.timer_elapsed_ms = 0
        self.min_warned = self.halfmin_warned = False
        self.waiting_for_ready = False
        self.manual_white = None
        self._all_white()
        print("Reset to waiting")

    def _expire_web_command(self):
        """Drop a web command nobody handled in time, so it can't fire later."""
        if self.web_command and now_s() - self.web_command_time > WEB_COMMAND_TTL_S:
            self.web_command = None
            self.web_command_value = None

    def status_dict(self):
        """Everything the overlay, banner and controller pages show."""
        remaining = max(0, self.match_length_ms - self.timer_elapsed_ms)
        secs = int(remaining / 1000)
        return {
            'time_str':          f"{secs // 60}:{secs % 60:02d}",
            'state':             self.state,
            'team1':             self.team1_name,
            'team2':             self.team2_name,
            'teams_set':         self.teams_set,
            'weight':            self.weight_class,
            'white':             self.white_on,
            'red_ready':         self.red_ready_shown,
            'blue_ready':        self.blue_ready_shown,
            'timer_color':       'flash' if self.start_sequence else self.timer_color,
            'start_countdown':   self.start_countdown_sec,
            'waiting_for_ready': self.waiting_for_ready,
        }

    def run(self):
        print("Controller running")
        for _ in range(3):
            self._all_white()
            time.sleep(0.1)
        try:
            while True:
                self._expire_web_command()

                if self._reset_requested():
                    self._reset()
                elif self.state == 0: self._state_0_waiting()
                elif self.state == 1: self._state_1_match()
                elif self.state == 2: self._state_2_paused()
                elif self.state == 3: self._state_3_complete()

                self.screen.draw(self.timer_elapsed_ms, self.match_length_ms, self.state)
                time.sleep(0.02)
        except KeyboardInterrupt:
            print("Shutting down")
        finally:
            self._led_fill(0, 0, 0)
            self.set_white_light(False)
            try:
                self.pixels.deinit()
            except Exception:
                pass
            GPIO.cleanup()
            self.screen.close()

# ==================== LIVE STATUS PUSH ====================
# The overlay, banner and controller pages used to each poll /status 20 times a
# second on their own timers, so they drifted apart (banner updating before the
# overlay) and flooded a weak Wi-Fi link. Now the Pi PUSHES one update to every
# page at the same moment over /events (server-sent events). Pages reconnect
# themselves if the link drops.

class StatusHub:
    def __init__(self):
        self.cond    = threading.Condition()
        self.version = 0
        self.payload = "{}"

    def publish(self, payload):
        with self.cond:
            self.payload = payload
            self.version += 1
            self.cond.notify_all()

# ==================== FLASK APP ====================

logging.getLogger('werkzeug').setLevel(logging.ERROR)   # no per-request console spam

app        = Flask(__name__)
controller = ArenaController()
hub        = StatusHub()

def _publisher():
    """Watches the controller state and pushes it whenever it changes (and as a
    heartbeat). Runs on its own thread, so updates still go out while the main
    loop is busy inside the start countdown."""
    last, last_sent = None, 0.0
    while True:
        try:
            d = controller.status_dict()
            now = now_s()
            if d != last or now - last_sent >= STATUS_HEARTBEAT_S:
                hub.publish(json.dumps(d))
                last, last_sent = d, now
        except Exception as e:
            print(f"Status publisher error: {e}")
        time.sleep(STATUS_POLL_S)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/command/<cmd>')
def send_command(cmd):
    # Value and timestamp first, command last, so the controller never sees a
    # command whose value hasn't arrived yet.
    controller.web_command_value = request.args.get('time')
    controller.web_command_time  = now_s()
    controller.web_command       = cmd
    return "OK", 200

@app.route('/press/<team>/<color>')
def press(team, color):
    name = f"{team}_{color}"
    if name in controller.PIN_NAMES.values():
        controller.web_presses[name] = now_s()
        return "OK", 200
    return "Bad button", 400

@app.route('/setteams')
def set_teams():
    controller.team1_name = request.args.get('team1', '').strip()
    controller.team2_name = request.args.get('team2', '').strip()
    controller.teams_set  = bool(controller.team1_name or controller.team2_name)
    print(f"Teams set: {controller.team1_name} vs {controller.team2_name}")
    return "OK", 200

@app.route('/white/<mode>')
def white(mode):
    if mode == 'on':
        controller.manual_white = True
        controller.set_white_light(True)
    elif mode == 'off':
        controller.manual_white = False
        controller.set_white_light(False)
    else:
        # Toggle
        new_state = not controller.white_on
        controller.manual_white = new_state
        controller.set_white_light(new_state)
    return jsonify({'white': controller.white_on})

@app.route('/status')
def status():
    # Kept for debugging / anything still polling. The pages use /events.
    return jsonify(controller.status_dict())

@app.route('/events')
def events():
    def stream():
        last = -1
        while True:
            with hub.cond:
                hub.cond.wait_for(lambda: hub.version != last, timeout=15)
                version, payload = hub.version, hub.payload
            if version != last:
                last = version
                yield f"data: {payload}\n\n"
            else:
                yield ": ping\n\n"
    return Response(
        stream_with_context(stream()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )

@app.route('/overlay')
def overlay():
    return render_template('overlay.html')

@app.route('/banner')
def banner():
    return render_template('banner.html')

if __name__ == '__main__':
    hub.publish(json.dumps(controller.status_dict()))   # so a page that connects instantly has data
    threading.Thread(target=_publisher, daemon=True).start()
    threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False, threaded=True),
        daemon=True,
    ).start()
    controller.run()