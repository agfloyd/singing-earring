const http = require('http');
const fs = require('fs');
const path = require('path');
const { WebSocketServer } = require('ws');

const PORT = 3000;
const MIME = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
};

// Room storage: { code: { conductor: ws|null, singers: Map<ws, {part}> } }
const rooms = new Map();

function generateCode() {
  const chars = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'; // no ambiguous chars
  let code = '';
  for (let i = 0; i < 4; i++) code += chars[Math.floor(Math.random() * chars.length)];
  return rooms.has(code) ? generateCode() : code;
}

function broadcastRoomState(room, code) {
  const counts = { soprano: 0, alto: 0, tenor: 0, bass: 0 };
  for (const info of room.singers.values()) {
    counts[info.part] = (counts[info.part] || 0) + 1;
  }
  const msg = JSON.stringify({ t: 'r', code, singers: counts });
  if (room.conductor && room.conductor.readyState === 1) room.conductor.send(msg);
  for (const ws of room.singers.keys()) {
    if (ws.readyState === 1) ws.send(msg);
  }
}

// Static file server
const server = http.createServer((req, res) => {
  let filePath = path.join(__dirname, 'public', req.url === '/' ? 'index.html' : req.url);
  const ext = path.extname(filePath);
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
    res.end(data);
  });
});

const wss = new WebSocketServer({ server });

wss.on('connection', (ws) => {
  let myRoom = null;
  let myCode = null;
  let myRole = null;

  ws.on('message', (raw) => {
    let msg;
    try { msg = JSON.parse(raw); } catch { return; }

    if (msg.t === 'create') {
      // Conductor creates a room
      const code = generateCode();
      rooms.set(code, { conductor: ws, singers: new Map() });
      myRoom = rooms.get(code);
      myCode = code;
      myRole = 'conductor';
      ws.send(JSON.stringify({ t: 'created', code }));

    } else if (msg.t === 'join') {
      // Singer joins a room
      const code = (msg.code || '').toUpperCase();
      const room = rooms.get(code);
      if (!room) {
        ws.send(JSON.stringify({ t: 'error', msg: 'Room not found' }));
        return;
      }
      room.singers.set(ws, { part: msg.part });
      myRoom = room;
      myCode = code;
      myRole = 'singer';
      ws.send(JSON.stringify({ t: 'joined', code }));
      broadcastRoomState(room, code);

    } else if (msg.t === 'n' && myRole === 'conductor' && myRoom) {
      // Note assignment from conductor — relay to all singers
      const raw = JSON.stringify(msg);
      for (const ws of myRoom.singers.keys()) {
        if (ws.readyState === 1) ws.send(raw);
      }

    } else if (msg.t === 'part' && myRole === 'singer' && myRoom) {
      // Singer changes their part
      const info = myRoom.singers.get(ws);
      if (info) {
        info.part = msg.part;
        broadcastRoomState(myRoom, myCode);
      }
    }
  });

  ws.on('close', () => {
    if (!myRoom) return;
    if (myRole === 'conductor') {
      // Notify all singers
      for (const s of myRoom.singers.keys()) {
        if (s.readyState === 1) s.send(JSON.stringify({ t: 'ended' }));
      }
      rooms.delete(myCode);
    } else {
      myRoom.singers.delete(ws);
      broadcastRoomState(myRoom, myCode);
      // Clean up empty rooms with no conductor
      if (!myRoom.conductor && myRoom.singers.size === 0) {
        rooms.delete(myCode);
      }
    }
  });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Singing Earring server running on http://0.0.0.0:${PORT}`);
  // Show local IP for sharing
  const nets = require('os').networkInterfaces();
  for (const iface of Object.values(nets)) {
    for (const addr of iface) {
      if (addr.family === 'IPv4' && !addr.internal) {
        console.log(`  Share this with singers: http://${addr.address}:${PORT}`);
      }
    }
  }
});
