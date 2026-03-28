#!/usr/bin/env python3
"""Singing Earring server — WebSocket relay + static file serving."""
import argparse
import asyncio
import json
import os
import random
import socket
from http import HTTPStatus
from pathlib import Path

import websockets
from websockets.http11 import Response

PORT = 3000
PUBLIC_DIR = Path(__file__).parent / "public"
TEST_MODE = False
TEST_CODE = "TEST"
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
}

# Room storage
rooms: dict = {}
# Default lobby config: presets from active parts, show name field
DEFAULT_LOBBY = {"nameMode": "optional", "namePosition": "top", "presets": None}  # None = use active parts

CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ"


def generate_code():
    while True:
        code = "".join(random.choices(CODE_CHARS, k=4))
        if code not in rooms:
            return code


PART_DISPLAY_NAMES = {
    "soprano": "Soprano", "alto": "Alto", "tenor": "Tenor", "bass": "Bass",
    "treble": "Treble", "baritone": "Baritone", "mezzo": "Mezzo-Soprano",
    "soprano1": "Soprano I", "soprano2": "Soprano II",
    "alto1": "Alto I", "alto2": "Alto II",
    "tenor1": "Tenor I", "tenor2": "Tenor II",
    "bass1": "Bass I", "bass2": "Bass II",
    "baritone1": "Baritone I", "baritone2": "Baritone II",
    "mezzo1": "Mezzo I", "mezzo2": "Mezzo II",
}


def auto_assign_name(room, part):
    """Generate a name like 'Alto #2' based on how many unnamed singers share this part category."""
    # Get base part name (strip trailing digits for sub-parts)
    base = part.rstrip("0123456789")
    display = PART_DISPLAY_NAMES.get(part, PART_DISPLAY_NAMES.get(base, part.capitalize()))
    # Count existing unnamed singers with the same base part
    count = 0
    for info in room["singers"].values():
        if not info.get("custom_name"):
            singer_base = info["part"].rstrip("0123456789")
            if singer_base == base:
                count += 1
    return f"{display} #{count + 1}"


def broadcast_room_state(room, code):
    singer_list = [{"id": info["id"], "part": info["part"], "range": info.get("range"), "name": info.get("name")} for info in room["singers"].values()]
    msg = json.dumps({"t": "r", "code": code, "singers": singer_list})
    targets = list(room["singers"].keys())
    if room["conductor"]:
        targets.append(room["conductor"])
    websockets.broadcast(targets, msg)


def serve_static(connection, request):
    """process_request hook: serve static files, pass WebSocket upgrades through."""
    # Let WebSocket upgrades pass
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None

    path = request.path.split("?")[0]  # Strip query params
    if path == "/":
        path = "/index.html"
    if path == "/conductor":
        path = "/conductor.html"

    file_path = (PUBLIC_DIR / path.lstrip("/")).resolve()

    # Security: prevent path traversal
    if not str(file_path).startswith(str(PUBLIC_DIR.resolve())):
        return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden")

    if not file_path.is_file():
        return connection.respond(HTTPStatus.NOT_FOUND, "Not found")

    # Read and serve the file
    ext = file_path.suffix
    content_type = MIME_TYPES.get(ext, "application/octet-stream")
    body = file_path.read_text() if content_type.startswith("text/") else file_path.read_bytes()

    return Response(
        status_code=200,
        reason_phrase="OK",
        headers=websockets.Headers([
            ("Content-Type", content_type),
            ("Content-Length", str(len(body.encode() if isinstance(body, str) else body))),
            ("Cache-Control", "no-cache"),
        ]),
        body=body.encode() if isinstance(body, str) else body,
    )


async def handler(websocket):
    my_room = None
    my_code = None
    my_role = None

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            t = msg.get("t")

            if t == "create":
                if TEST_MODE:
                    code = TEST_CODE
                    # Reuse existing test room or create fresh
                    if code in rooms:
                        rooms[code]["conductor"] = websocket
                    else:
                        rooms[code] = {"conductor": websocket, "singers": {}, "next_id": 0, "lobby": {"nameMode": "optional", "namePosition": "top", "presets": None}}
                else:
                    code = generate_code()
                    rooms[code] = {"conductor": websocket, "singers": {}, "next_id": 0, "lobby": {"nameMode": "optional", "namePosition": "top", "presets": None}}
                my_room = rooms[code]
                my_code = code
                my_role = "conductor"
                await websocket.send(json.dumps({"t": "created", "code": code, "ip": get_local_ip(), "port": PORT}))

            elif t == "check":
                # Singer checking if room exists before joining — return lobby config
                code = (msg.get("code") or "").upper()
                room = rooms.get(code)
                if not room:
                    if TEST_MODE:
                        rooms[code] = {"conductor": None, "singers": {}, "next_id": 0, "lobby": {"nameMode": "optional", "namePosition": "top", "presets": None}}
                        room = rooms[code]
                    else:
                        await websocket.send(json.dumps({"t": "error", "msg": "Room not found"}))
                        continue
                lobby = room.get("lobby", {"nameMode": "optional", "namePosition": "top", "presets": None})
                presets = lobby.get("presets")
                # If presets is None, derive from cached part config
                if presets is None and "partConfig" in room:
                    presets = [{"id": p["id"], "label": p.get("label", p["id"]), "color": p.get("color", "#888"), "range": p.get("range")} for p in room["partConfig"]]
                await websocket.send(json.dumps({"t": "lobby", "code": code, "nameMode": lobby.get("nameMode", "optional"), "namePosition": lobby.get("namePosition", "top"), "presets": presets}))

            elif t == "join":
                code = (msg.get("code") or "").upper()
                if TEST_MODE and not code:
                    code = TEST_CODE
                room = rooms.get(code)
                if not room:
                    if TEST_MODE:
                        # Auto-create room if conductor hasn't connected yet
                        rooms[code] = {"conductor": None, "singers": {}, "next_id": 0}
                        room = rooms[code]
                    else:
                        await websocket.send(json.dumps({"t": "error", "msg": "Room not found"}))
                        continue
                room["next_id"] = room.get("next_id", 0) + 1
                singer_id = room["next_id"]
                part = msg.get("part", "soprano")
                custom_name = msg.get("name", "").strip()
                name = custom_name or auto_assign_name(room, part)
                room["singers"][websocket] = {
                    "id": singer_id,
                    "part": part,
                    "range": msg.get("range"),
                    "name": name,
                    "custom_name": bool(custom_name),
                }
                my_room = room
                my_code = code
                my_role = "singer"
                await websocket.send(json.dumps({"t": "joined", "code": code, "id": singer_id, "name": name}))
                broadcast_room_state(room, code)

            elif t == "lobbyConfig" and my_role == "conductor" and my_room:
                # Conductor updating lobby configuration
                lobby = my_room.get("lobby", {})
                if "nameMode" in msg:
                    lobby["nameMode"] = msg["nameMode"]
                if "namePosition" in msg:
                    lobby["namePosition"] = msg["namePosition"]
                if "presets" in msg:
                    lobby["presets"] = msg["presets"]  # list of {id, label, color, range} or None
                my_room["lobby"] = lobby

            elif t in ("n", "syl", "vol", "parts") and my_role == "conductor" and my_room:
                if t == "parts":
                    # Cache part config on the room for lobby presets
                    my_room["partConfig"] = msg.get("parts", [])
                raw_msg = json.dumps(msg)
                websockets.broadcast(list(my_room["singers"].keys()), raw_msg)

            elif t == "part" and my_role == "singer" and my_room:
                info = my_room["singers"].get(websocket)
                if info:
                    info["part"] = msg.get("part", info["part"])
                    if "range" in msg:
                        info["range"] = msg["range"]
                    broadcast_room_state(my_room, my_code)

    finally:
        if my_room and my_code:
            if my_role == "conductor":
                ended = json.dumps({"t": "ended"})
                websockets.broadcast(list(my_room["singers"].keys()), ended)
                rooms.pop(my_code, None)
            elif my_role == "singer":
                my_room["singers"].pop(websocket, None)
                if my_code in rooms:
                    broadcast_room_state(my_room, my_code)
                if not my_room["conductor"] and not my_room["singers"]:
                    rooms.pop(my_code, None)


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


async def main():
    async with websockets.serve(
        handler,
        "0.0.0.0",
        PORT,
        process_request=serve_static,
        compression=None,
    ):
        local_ip = get_local_ip()
        if TEST_MODE:
            print(f"Singing Earring server running in TEST MODE on http://0.0.0.0:{PORT}")
            print(f"  Room code: {TEST_CODE} (fixed)")
            print(f"  Conductor: http://{local_ip}:{PORT}/conductor?test")
            print(f"  Singers:   http://{local_ip}:{PORT}?test")
        else:
            print(f"Singing Earring server running on http://0.0.0.0:{PORT}")
            print(f"  Conductor: http://{local_ip}:{PORT}/conductor")
            print(f"  Singers:   http://{local_ip}:{PORT}")
        await asyncio.Future()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Singing Earring server")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: fixed room code TEST, auto-join for singers")
    args = parser.parse_args()
    TEST_MODE = args.test
    asyncio.run(main())
