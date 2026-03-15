# Singing Earring

A real-time web app for group singing events. A conductor plays chords on a MIDI keyboard (or on-screen piano), and each participant's phone plays their assigned voice part (Soprano/Alto/Tenor/Bass) through headphones so they can pitch-match and sing together.

Designed for ultra-low latency (<50ms) on a local WiFi network.

## How it works

1. **Conductor** opens the conductor page on a laptop, creating a room with a 4-letter code
2. **Singers** open the app on their phones, enter the room code, and pick their voice part (S/A/T/B)
3. Conductor plays chords — each singer's phone synthesizes their assigned note locally using the Web Audio API
4. Everyone sings along with their tone as a pitch reference

The app uses WebSockets for near-instant message relay and local oscillator synthesis on each device, so there's no audio streaming and latency stays minimal.

## Setup

```bash
git clone https://github.com/agfloyd/singing-earring.git
cd singing-earring
python3 -m venv .venv
source .venv/bin/activate
pip install websockets
python3 server.py
```

The server prints the local IP address and URLs to share.

## Testing mode

For development/testing with a fixed room code and auto-join:

```bash
python3 server.py --test
```

Then open:
- **Conductor:** `http://<your-ip>:3000/conductor?test`
- **Singer:** `http://<your-ip>:3000/?test` (just pick a part and you're in)

## Conductor keyboard mapping

The laptop keyboard maps to piano keys with white keys on the QWERTY row and black keys on the number row (matching the physical layout of a piano):

```
Black:  2  3     5  6  7     9  0     -  =
White: Q  W  E  R  T  Y  U  I  O  P  [  ]  \   L  ;
Note:  C3 D3 E3 F3 G3 A3 B3 C4 D4 E4 F4 G4 A4  B4 C5
```

**Special keys:**
- `1` — Hissing: the worst-fitting voice part plays a shh/hiss sound
- `4` — Rubbing hands: all singers see a "rub hands together" instruction

MIDI keyboards are also supported (Chrome only) and take priority when connected.

## Features

- **Voice assignment algorithm**: Every held note is guaranteed at least one singer. When there are fewer notes than parts, extra parts double up on the nearest note. Only parts with active singers receive assignments.
- **Part-colored piano keys**: Conductor's piano keys light up in the assigned part's color (gradient stripes when multiple parts share a note)
- **Range indicators**: L/J-shaped colored ticks below the piano show each part's singable range
- **Singer controls**: Change part without leaving the room, mini keyboard showing current note, mute button with Auto/Manual modes
- **Singing bowl tone**: Warm, shimmering synthesis using layered detuned sine oscillators
- **Screen-off persistence**: Silent audio keep-alive + auto-reconnect keeps the app working even when the phone screen turns off
- **iOS compatibility**: AudioContext unlock on user gesture, mute switch warning

## Architecture

```
┌──────────────┐     WebSocket     ┌─────────────┐
│  Conductor   │ ───────────────── │   Server    │
│  (laptop)    │   note messages   │  (Python)   │
│              │                   │             │
│  MIDI/Piano  │                   │  Room mgmt  │
│  Voice assign│                   │  Msg relay  │
└──────────────┘                   └──────┬──────┘
                                          │ broadcast
                          ┌───────────────┼───────────────┐
                          │               │               │
                    ┌─────┴──────┐  ┌─────┴──────┐  ┌─────┴──────┐
                    │  Singer 1  │  │  Singer 2  │  │  Singer 3  │
                    │  (phone)   │  │  (phone)   │  │  (phone)   │
                    │            │  │            │  │            │
                    │  Web Audio │  │  Web Audio │  │  Web Audio │
                    │  oscillator│  │  oscillator│  │  oscillator│
                    └────────────┘  └────────────┘  └────────────┘
```

## Tips for the event

- Use **wired headphones** — Bluetooth adds 100-300ms of latency
- iOS users: make sure the **mute switch is OFF**
- The conductor's laptop and all phones should be on the **same WiFi network**
- **Auto-mute mode** is great for singers who want a brief pitch reference then silence to focus on listening to the group
