//adafruit neopixel library setup
#include <Adafruit_NeoPixel.h>
#ifdef __AVR__
#include <avr/power.h>
#endif
#define PIN        9
#define NUMPIXELS 197
#define team1Length 97
#define team2Length 100

// Brightness 255 with every pixel white is the worst-case current draw (~60 mA per pixel at
// full white, so ~12 A for 197 pixels). Make sure the LED supply can handle it, or lower this.
#define LED_BRIGHTNESS 255

Adafruit_NeoPixel pixels(NUMPIXELS, PIN, NEO_GRB + NEO_KHZ800);

  /* welcome to the V1 beetle arena controller code if you are an arena controller here is what you need to know:
  serial input is enabled and can act as an arena controller all on its own!
  here are the keys you need to know:

  f: fight start, also unpause when in unstick state (state 2)
  spacebar: end match (also cancels a countdown)
  r: reset after a match
  u: unstick

note: these are case sensitive. Serial Monitor line endings (newline / carriage return) are ignored.

  states (printed as "state: N" whenever it changes):
  0 idle - waiting for both teams to ready up
  1 fight - match running, timer counting
  2 paused - unstick / override pause, timer stopped
  3 match over - lights stay red until reset
  4 countdown - red flashes before FIGHT (on start and on unpause)

  nothing in loop() blocks anymore (no delay()), so buttons and serial keys are read the whole
  time, including during sounds and the countdown.
 */

//definitions
  /* code is set up for an arduino mega: buttons are wired between the input pin and GND and use
  the internal pull-up, so a pressed button reads LOW.
  to move to an ESP32: change BUTTON_MODE to INPUT_PULLDOWN and BUTTON_PRESSED to HIGH, wire the
  buttons to 3.3v instead of GND, and pick pin numbers that exist on the ESP32 (22-37 mostly don't). */
  #define BUTTON_MODE    INPUT_PULLUP
  #define BUTTON_PRESSED LOW

  //game states
  #define STATE_IDLE      0
  #define STATE_FIGHT     1
  #define STATE_PAUSED    2
  #define STATE_OVER      3
  #define STATE_COUNTDOWN 4

  //computer inputs
    char receivedChar = 0;   // 0 = no key this loop

  //declare audio pins
    const int audio_Ready_team1 = 3;
    const int audio_Ready_team2 = 4;
    const int audio_fight_pin = 5;
    const int audio_1_minute = 6;
    const int audio_30_seconds = 7;
    const int audio_fight_end = 8;


  // declare button inputs
    //gnd pins bc im short on time and dont want to solder even more shit
    const int team_1_green = 22;
    const int team_1_green_gnd = 23;

    const int team_2_green = 24;
    const int team_2_green_gnd = 25;

    const int team_1_red = 26;
    const int team_1_red_gnd = 27;

    const int team_2_red = 28;
    const int team_2_red_gnd = 29;

  //override controller buttons
    //this system just uses an arduino gnd pin for the moment
    const int controller_start = 33;
    const int controller_pause = 35;
    const int controller_stop = 37;

    // wired and set up as inputs, but not used by the code yet
    const int controller_timer_add = 32;
    const int controller_timer_subtract = 34;
    const int controller_reset = 36;

  // tracks game state
    int state = STATE_IDLE;

  // memory storage for ready buttons
    bool ready1 = false;
    bool ready2 = false;

  //memory for timer announcments
    bool min_triggered = false;
    bool half_min_triggered = false;

  // match timer: only counts while in STATE_FIGHT, so pauses and countdowns don't use up match time
    unsigned long timer = 0;               // ms of fight time used so far
    unsigned long timer_last_millis = 0;
    unsigned long last_printed_second = 0;

  // set match length
    const unsigned long match_length_millis = 3UL * 60UL * 1000UL;

  // countdown: wait countdown_lead ms, then red on / off / red / off / red (1 s each), then FIGHT
    #define COUNTDOWN_STEPS 5
    unsigned long countdown_start = 0;
    unsigned long countdown_lead = 0;
    int countdown_step = -1;

  // the lights stay blue for 2 s after FIGHT, then go white
    #define FIGHT_LIGHT_MS 2000UL
    bool fight_light_on = false;
    unsigned long fight_light_since = 0;

  // audio: a sound plays while its trigger pin is held LOW. Sounds are queued and played one at a
  // time (same order and hold times as before) without stopping the loop.
    #define AUDIO_QUEUE_SIZE 6
    #define AUDIO_GAP_MS 50UL                // pin goes HIGH this long between two sounds
    int audio_queue_pin[AUDIO_QUEUE_SIZE];
    unsigned long audio_queue_ms[AUDIO_QUEUE_SIZE];
    int audio_queue_count = 0;
    int audio_active_pin = -1;               // -1 = nothing playing
    unsigned long audio_started = 0;
    unsigned long audio_hold_ms = 0;
    unsigned long audio_released = 0;




void setup() {
  // put your setup code here, to run once:
    Serial.begin(9600);
    Serial.println("<Arduino is ready>");

  //audio plays when a pin is pulled low - set all audio control pins high
    pinMode(audio_Ready_team1, OUTPUT);
    pinMode(audio_Ready_team2, OUTPUT);
    pinMode(audio_fight_pin, OUTPUT);
    pinMode(audio_1_minute, OUTPUT);
    pinMode(audio_30_seconds, OUTPUT);
    pinMode(audio_fight_end, OUTPUT);

    digitalWrite(audio_Ready_team1, HIGH);
    digitalWrite(audio_Ready_team2, HIGH);
    digitalWrite(audio_fight_pin, HIGH);
    digitalWrite(audio_1_minute, HIGH);
    digitalWrite(audio_30_seconds, HIGH);
    digitalWrite(audio_fight_end, HIGH);

    pinMode(team_1_green, BUTTON_MODE);
    pinMode(team_2_green, BUTTON_MODE);
    pinMode(team_1_red, BUTTON_MODE);
    pinMode(team_2_red, BUTTON_MODE);

  //when using pullup! - arduino pins used as GND for the team buttons
    pinMode(team_1_green_gnd, OUTPUT);
    pinMode(team_2_green_gnd, OUTPUT);
    pinMode(team_1_red_gnd, OUTPUT);
    pinMode(team_2_red_gnd, OUTPUT);
    digitalWrite(team_1_green_gnd, LOW);
    digitalWrite(team_2_green_gnd, LOW);
    digitalWrite(team_1_red_gnd, LOW);
    digitalWrite(team_2_red_gnd, LOW);

    pinMode(controller_start, BUTTON_MODE);
    pinMode(controller_pause, BUTTON_MODE);
    pinMode(controller_stop, BUTTON_MODE);

    pinMode(controller_reset, BUTTON_MODE);
    pinMode(controller_timer_subtract, BUTTON_MODE);
    pinMode(controller_timer_add, BUTTON_MODE);

  //led initialization
    #if defined(__AVR_ATtiny85__) && (F_CPU == 16000000)
      clock_prescale_set(clock_div_1);
    #endif
      pixels.begin();

    pixels.setBrightness(LED_BRIGHTNESS);
    color_fill(255,255,255);
    setState(STATE_IDLE);
}

void loop()
{
  recvOneChar();
  updateAudio();

  // Finite state machine
  // LEDs are only redrawn when something changes. pixels.show() turns interrupts off for ~6 ms
  // on 197 pixels, so calling it every loop made millis() (and the match timer) run slow.
  switch (state){
    case STATE_IDLE:
      // team 1 ready up
      if (pressed(team_1_green) && (ready1 == false))
      {
        ready1 = true;
        pixels.fill(pixels.Color(255,0,0),0,team1Length);
        pixels.show();
        Serial.println("team 1 ready");
        triggerAudio(audio_Ready_team1,3000);
      }

      //team 2 ready up
      if (pressed(team_2_green) && (ready2 == false))
      {
        ready2 = true;
        pixels.fill(pixels.Color(0,255,0),team1Length,team2Length);
        pixels.show();
        Serial.println("team 2 ready");
        triggerAudio(audio_Ready_team2,3000);
      }

      //check start conditon
      if ((ready1 && ready2) || pressed(controller_start) || (receivedChar == 'f'))
      {
        // STATE 0->4->1 transition logic
        Serial.println("0->1 transition start");
        timer = 0;
        last_printed_second = 0;
        min_triggered = false;
        half_min_triggered = false;

        //reset ready 1 & 2 to be used later
        ready1 = false;
        ready2 = false;
        startCountdown(2000);
      }
      break;


    case STATE_COUNTDOWN:
      // stop during the countdown ends the match instead of being ignored
      if (pressed(controller_stop) || (receivedChar == ' '))
      {
        endMatch(false, "countdown stopped");
        break;
      }
      {
        unsigned long elapsed = millis() - countdown_start;
        if (elapsed < countdown_lead)
          break;   // lights stay as they were
        int step = (elapsed - countdown_lead) / 1000;
        if (step >= COUNTDOWN_STEPS)
        {
          startFight();
          break;
        }
        if (step != countdown_step)
        {
          countdown_step = step;
          if (step % 2 == 0)
            color_fill(255,0,0);
          else
          {
            pixels.clear();
            pixels.show();
          }
        }
      }
      break;


    case STATE_FIGHT:
      {
        //in match - countdown active
        //delta time implemetation - in short a time tracker
        unsigned long current_millis = millis();
        timer += current_millis - timer_last_millis;
        timer_last_millis = current_millis;

        // blue FIGHT light for 2 s, then white
        if (fight_light_on && (current_millis - fight_light_since >= FIGHT_LIGHT_MS))
        {
          fight_light_on = false;
          color_fill(255,255,255);
        }

        //timer debug, once a second instead of every loop
        if (timer / 1000 != last_printed_second)
        {
          last_printed_second = timer / 1000;
          Serial.print("time: ");
          Serial.println(last_printed_second);
        }
      }

      if (timer >= match_length_millis)
      {
        //if the timer is up transition to match end
        endMatch(true, "match time over");
        break;
      }

      //tapout
      if (pressed(team_1_red) || pressed(team_2_red) || pressed(controller_stop) || (receivedChar == ' '))
      {
        //end match for tapout or override
        endMatch(true, "tapout");
        break;
      }

      //unstick
      if (pressed(team_1_green) || pressed(team_2_green) || pressed(controller_pause) || (receivedChar == 'u'))
      {
        //pause match for unstick or override
        //state 1->2 transition logic
        fight_light_on = false;
        //led to yellow
        color_fill(255,255,0);
        Serial.println("fight paused");
        triggerAudio(audio_fight_end,3000);
        setState(STATE_PAUSED);
        break;
      }

      //1 minute left
      if ((timer + 60000UL >= match_length_millis) && (min_triggered == false))
      {
        min_triggered = true;
        triggerAudio(audio_1_minute,3000);
        Serial.println("1 minute left");
      }

      //30 seconds left
      if ((timer + 30000UL >= match_length_millis) && (half_min_triggered == false))
      {
        half_min_triggered = true;
        triggerAudio(audio_30_seconds,3000);
        Serial.println("30 seconds left");
      }
      break;


    case STATE_PAUSED:
      // match paused
      if (pressed(controller_stop) || (receivedChar == ' '))
      {
        // stop match 2->3 transition
        endMatch(false, "controller override stop");
        break;
      }

      if (pressed(controller_start) || (receivedChar == 'f'))
      {
        // unpause 2->4->1: redo start sequence
        Serial.println("fight unpaused");
        startCountdown(1000);
      }
      break;


    case STATE_OVER:
      //match complete - lights stay red until reset
      if (pressed(controller_reset) || (receivedChar == 'r'))
      {
        color_fill(255,255,255);
        Serial.println("reset");
        setState(STATE_IDLE);
      }
      break;
  }
}

// ---------- state transitions ----------

void setState(int new_state)
{
  state = new_state;
  Serial.print("state: ");
  Serial.println(state);
}

void startCountdown(unsigned long lead_ms)
{
  countdown_start = millis();
  countdown_lead = lead_ms;
  countdown_step = -1;
  setState(STATE_COUNTDOWN);
}

void startFight()
{
  // FIGHT: sound, blue lights and the match timer all start together
  triggerAudio(audio_fight_pin,2000);
  color_fill(0,0,255);
  fight_light_on = true;
  fight_light_since = millis();
  timer_last_millis = millis();
  Serial.println("match start");
  setState(STATE_FIGHT);
}

void endMatch(bool play_sound, const char *reason)
{
  if (play_sound)
    triggerAudio(audio_fight_end,1000);
  Serial.println(reason);
  fightEndAnim();
  setState(STATE_OVER);
}

void fightEndAnim(){
  //fight stop anim - red until reset
  fight_light_on = false;
  color_fill(255,0,0);
}

// ---------- helpers ----------

bool pressed(int pin)
{
  return digitalRead(pin) == BUTTON_PRESSED;
}

void color_fill(int color1, int color2, int color3)
{
  pixels.fill(pixels.Color(color1,color2,color3));
  pixels.show();
}

void recvOneChar() {
  receivedChar = 0;
  if (Serial.available() > 0) {
    char c = Serial.read();
    if ((c == '\n') || (c == '\r'))
      return;   // Serial Monitor line endings aren't commands
    receivedChar = c;
    Serial.print("This just in ... ");
    Serial.println(receivedChar);
  }
}

// queue a sound: its pin is pulled LOW for hold_ms once the sounds before it have finished
void triggerAudio(int pin, unsigned long hold_ms)
{
  if (audio_queue_count >= AUDIO_QUEUE_SIZE)
    return;   // queue full (shouldn't happen in normal use), drop the sound
  audio_queue_pin[audio_queue_count] = pin;
  audio_queue_ms[audio_queue_count] = hold_ms;
  audio_queue_count++;
}

// call every loop: releases the playing pin when its time is up and starts the next sound
void updateAudio()
{
  unsigned long now = millis();
  if (audio_active_pin >= 0)
  {
    if (now - audio_started < audio_hold_ms)
      return;
    digitalWrite(audio_active_pin, HIGH);
    audio_active_pin = -1;
    audio_released = now;
  }
  if ((audio_queue_count == 0) || (now - audio_released < AUDIO_GAP_MS))
    return;

  audio_active_pin = audio_queue_pin[0];
  audio_hold_ms = audio_queue_ms[0];
  for (int i = 1; i < audio_queue_count; i++)
  {
    audio_queue_pin[i - 1] = audio_queue_pin[i];
    audio_queue_ms[i - 1] = audio_queue_ms[i];
  }
  audio_queue_count--;
  audio_started = now;
  digitalWrite(audio_active_pin, LOW);
}
