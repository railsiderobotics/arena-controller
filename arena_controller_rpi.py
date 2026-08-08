#!/usr/bin/env python3
# authbind /home/railside/arena_controller/arena_env/bin/python3 "%f"

import time
import threading
import RPi.GPIO as GPIO
import board
import neopixel
import pygame
from flask import Flask, render_template, request, jsonify

# ==================== SCREEN CONFIGURATION ====================

SCREEN_WIDTH  = 800
SCREEN_HEIGHT = 550

# ==================== CONFIGURATION ====================

MATCH_LENGTH_SECONDS = 180  # beetle (3 min)
ANT_LENGTH_SECONDS   = 120  # ant (2 min)

NUMPIXELS  = 197
TEAM1_LEN  = 97
TEAM2_LEN  = 100

# GPIO pin numbers (BCM)
TEAM1_GREEN      = 2
TEAM2_GREEN      = 3
TEAM1_RED        = 4
TEAM2_RED        = 5
TEAM1_YELLOW     = 6
TEAM2_YELLOW     = 7
CONTROLLER_START = 8
CONTROLLER_RESET = 9

DEBOUNCE_S = 0.3   # seconds between accepted button presses

# ==================== SCREEN DISPLAY ====================

class ScreenDisplay:
    STATE_LABELS = {
        0: ((128, 128, 128), "WAITING FOR TEAMS"),
        1: ((0,   0,   255), "MATCH IN PROGRESS"),
        2: ((255, 255,   0), "PAUSED"),
        3: ((255,   0,   0), "MATCH COMPLETE"),
    }

    def __init__(self):
        try:
            pygame.init()
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
            self.screen.fill((0, 0, 0))

            # Timer
            remaining = max(0, total_ms - elapsed_ms)
            secs = int(remaining / 1000)
            time_str = f"{secs // 60:02d}:{secs % 60:02d}"
            timer_surf = self.font_huge.render(time_str, True, (255, 255, 255))
            self.screen.blit(timer_surf, timer_surf.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 3)))

            # State label
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
        self.state             = 0
        self.ready1            = False
        self.ready2            = False
        self.timer_start       = 0.0
        self.timer_elapsed_ms  = 0
        self.match_length_ms   = MATCH_LENGTH_SECONDS * 1000
        self.min_warned        = False
        self.halfmin_warned    = False
        self._last_press       = {}
        self.team1_name        = "Team 1"
        self.team2_name        = "Team 2"

        self._setup_gpio()
        self.led = neopixel.NeoPixel(
            board.D18, NUMPIXELS, brightness=1.0, auto_write=True
        )
        self.led.fill((255, 255, 255))
        self.screen = ScreenDisplay()
        print("Arena Controller Initialized")

    # ── GPIO ────────────────────────────────────────────────────────────

    def _setup_gpio(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        pins = [
            TEAM1_GREEN, TEAM2_GREEN,
            TEAM1_RED,   TEAM2_RED,
            TEAM1_YELLOW, TEAM2_YELLOW,
            CONTROLLER_START, CONTROLLER_RESET,
        ]
        for pin in pins:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def _pressed(self, pin):
        """Return True once per debounce window when a pin goes LOW."""
        if GPIO.input(pin) != GPIO.LOW:
            return False
        now = time.time()
        if now - self._last_press.get(pin, 0) < DEBOUNCE_S:
            return False
        self._last_press[pin] = now
        return True

    # ── LED helpers ─────────────────────────────────────────────────────

    def _led_fill(self, r, g, b):
        self.led.fill((r, g, b))

    def _led_range(self, start, end, r, g, b):
        for i in range(start, min(end, NUMPIXELS)):
            self.led[i] = (r, g, b)

    def _start_animation(self):
        """3x red blink then solid blue for 2s."""
        for _ in range(3):
            time.sleep(1)
            self._led_fill(255, 0, 0)
            time.sleep(1)
            self._led_fill(0, 0, 0)
        self._led_fill(0, 0, 255)
        time.sleep(2)

    # ── State machine ────────────────────────────────────────────────────

    def _enter_match(self):
        """Shared logic for starting / resuming a match."""
        self._start_animation()
        self.timer_start = time.time()
        self.state = 1
        print("Match running")

    def _end_match(self):
        self.state = 3
        self.screen.draw(self.timer_elapsed_ms, self.match_length_ms, self.state)
        def animate():
            self._led_fill(255, 0, 0)
            time.sleep(5)
            self._led_fill(255, 255, 255)
        threading.Thread(target=animate, daemon=True).start()
        print("Match complete")

    def _state_0_waiting(self):
        """Wait for both teams to press Green (or web/controller start)."""
        if self._pressed(TEAM1_GREEN) and not self.ready1:
            self.ready1 = True
            self._led_range(0, TEAM1_LEN, 255, 0, 0)
            print("Team 1 ready")

        if self._pressed(TEAM2_GREEN) and not self.ready2:
            self.ready2 = True
            self._led_range(TEAM1_LEN, TEAM1_LEN + TEAM2_LEN, 0, 255, 0)
            print("Team 2 ready")

        start = (
            (self.ready1 and self.ready2)
            or self._pressed(CONTROLLER_START)
            or self.web_command in ('f', 'fa', 'fb')
        )
        if start:
            if self.web_command == 'fa':
                self.match_length_ms = ANT_LENGTH_SECONDS * 1000
                print("Ant class: 2 min match")
            elif self.web_command in ('fb', 'f'):
                self.match_length_ms = MATCH_LENGTH_SECONDS * 1000
                print("Beetle class: 3 min match")
            self.web_command = None
            self.ready1 = self.ready2 = False
            self.timer_elapsed_ms = 0
            self.min_warned = self.halfmin_warned = False
            self._enter_match()

    def _state_1_match(self):
        """Match running: update timer, check warnings and buttons."""
        self._led_fill(255, 255, 255)
        self.timer_elapsed_ms = (time.time() - self.timer_start) * 1000

        if self.timer_elapsed_ms >= self.match_length_ms - 60_000 and not self.min_warned:
            self.min_warned = True
            print("1 minute left")

        if self.timer_elapsed_ms >= self.match_length_ms - 30_000 and not self.halfmin_warned:
            self.halfmin_warned = True
            print("30 seconds left")

        # Time over or tapout
        if self.timer_elapsed_ms >= self.match_length_ms or self.web_command == 't':
            self.web_command = None
            print("Time over / tapout")
            self._end_match()
            return

        # Pause
        if (self._pressed(TEAM1_YELLOW) or self._pressed(TEAM2_YELLOW)
                or self.web_command == 'u'):
            self.web_command = None
            self.timer_elapsed_ms = (time.time() - self.timer_start) * 1000
            self.state = 2
            self.screen.draw(self.timer_elapsed_ms, self.match_length_ms, self.state)
            threading.Thread(target=lambda: self._led_fill(255, 255, 0), daemon=True).start()
            print("Match paused")
            return

        # Surrender
        if self._pressed(TEAM1_RED) or self._pressed(TEAM2_RED):
            self.web_command = None
            print("Tapout")
            self._end_match()

    def _state_2_paused(self):
        """Paused: Yellow again or web 'f' resumes; web 'r' resets."""
        # Time adjustment only allowed while paused
        if self.web_command == 'c':
            self._change_time()
            self.timer_elapsed_ms = (time.time() - self.timer_start) * 1000
            return

        resume = (
            self._pressed(TEAM1_YELLOW)
            or self._pressed(TEAM2_YELLOW)
            or self.web_command == 'f'
        )
        if resume:
            self.web_command = None
            self.timer_start = time.time() - self.timer_elapsed_ms / 1000
            self._enter_match()
            return

        if self.web_command == 'r':
            self.web_command = None
            self._reset()

    def _state_3_complete(self):
        """Match over: wait for reset."""
        if self._pressed(CONTROLLER_RESET) or self.web_command == 'r':
            self.web_command = None
            self._reset()

    def _change_time(self):
        """Add or subtract time (only while paused)."""
        if self.web_command_value is None:
            self.web_command = None
            return
        try:
            seconds = int(self.web_command_value)
            self.timer_start += seconds
            if seconds > 0:
                print(f"Added {seconds} seconds")
            elif seconds < 0:
                print(f"Subtracted {abs(seconds)} seconds")
        except ValueError:
            print("Invalid time value")
        self.web_command = None
        self.web_command_value = None

    def _reset(self):
        self.state = 0
        self.ready1 = self.ready2 = False
        self.timer_elapsed_ms = 0
        self.min_warned = self.halfmin_warned = False
        self._led_fill(255, 255, 255)
        print("Reset to waiting")

    # ── Main loop ────────────────────────────────────────────────────────

    def run(self):
        print("Controller running")
        try:
            while True:
                if   self.state == 0: self._state_0_waiting()
                elif self.state == 1: self._state_1_match()
                elif self.state == 2: self._state_2_paused()
                elif self.state == 3: self._state_3_complete()

                self.screen.draw(self.timer_elapsed_ms, self.match_length_ms, self.state)
                time.sleep(0.05)
        except KeyboardInterrupt:
            print("Shutting down")
        finally:
            self.led.fill((0, 0, 0))
            GPIO.cleanup()
            self.screen.close()

# ==================== FLASK APP ====================

app        = Flask(__name__)
controller = ArenaController()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/command/<cmd>')
def send_command(cmd):
    controller.web_command       = cmd
    controller.web_command_value = request.args.get('time')
    return "OK", 200

@app.route('/setteams')
def set_teams():
    controller.team1_name = request.args.get('team1', controller.team1_name).strip()
    controller.team2_name = request.args.get('team2', controller.team2_name).strip()
    print(f"Teams set: {controller.team1_name} vs {controller.team2_name}")
    return "OK", 200

@app.route('/status')
def status():
    remaining = max(0, controller.match_length_ms - controller.timer_elapsed_ms)
    secs = int(remaining / 1000)
    return jsonify({
        'time_str': f"{secs // 60}:{secs % 60:02d}",
        'state':    controller.state,
        'team1':    controller.team1_name,
        'team2':    controller.team2_name,
    })

@app.route('/overlay')
def overlay():
    return render_template('overlay.html')

if __name__ == '__main__':
    threading.Thread(
        target=lambda: app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False),
        daemon=True,
    ).start()
    controller.run()