#!/usr/bin/env python3
"""
TACTICAL WIFI SCANNER - ANDROID/TERMUX
Pure Python 3, No External Dependencies, HUD Interface
Optimized for Samsung OneUI / Android
"""

import http.server
import socketserver
import subprocess
import threading
import time
import json
import re
import os
import math
import hashlib
import sys
from datetime import datetime

# --- CONFIGURATION ---
PORT = 8080
SCAN_INTERVAL = 5
MAX_HISTORY = 30
GRID_SIZE = 100  # meters radius representation

# --- GLOBAL STATE ---
scan_data = {
    "signals": [],
    "timeline": [],
    "last_scan": None,
    "method": "initializing",
    "status": "idle"
}
data_lock = threading.Lock()

class AndroidScanner:
    def __init__(self):
        self.method = None
        self.interface = "wlan0"
        self.detect_method()

    def detect_method(self):
        """Auto-detects the best available scanning method."""
        methods = [
            ("iw", ["iw", "dev", self.interface, "scan"]),
            ("wpa_cli", ["wpa_cli", "-i", self.interface, "scan_results"]),
            ("dumpsys", ["dumpsys", "wifi"]),
            ("proc", ["cat", "/proc/net/wireless"])
        ]

        print("[-] Detecting scan capabilities...")
        
        # Check root for iw/wpa
        is_root = os.geteuid() == 0
        
        for name, cmd in methods:
            try:
                # Root checks for iw/wpa
                if name in ["iw", "wpa_cli"] and not is_root:
                    continue
                    
                # Test execution
                proc = subprocess.run(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    timeout=2,
                    encoding='utf-8', 
                    errors='ignore'
                )
                
                if proc.returncode == 0 and len(proc.stdout) > 50:
                    self.method = name
                    print(f"[+] Method detected: {name.upper()}")
                    return
            except Exception:
                continue

        # Fallback for non-root without dumpsys permission
        self.method = "demo" 
        print("[!] No physical scan method available (Permission/Root required). Using DEMO MODE.")

    def calculate_distance(self, rssi, freq=2400):
        """Estimates distance based on FSPL model."""
        try:
            exp = (27.55 - (20 * math.log10(freq)) + abs(rssi)) / 20.0
            return round(10 ** exp, 2)
        except:
            return 0.0

    def calculate_risk(self, signal):
        """Calculates risk score (0-100)."""
        score = 0
        enc = signal.get('encryption', '').upper()
        rssi = signal.get('rssi', -100)
        ssid = signal.get('ssid', '')

        # Encryption Risk
        if "OPEN" in enc or enc == "": score += 50
        elif "WEP" in enc: score += 40
        elif "WPA" in enc and "WPA2" not in enc: score += 25
        
        # Signal Risk (Closer = Higher Risk)
        if rssi > -50: score += 30
        elif rssi > -70: score += 15
        
        # Hidden Network
        if not ssid or "\\x00" in ssid: score += 20

        return min(score, 100)

    def generate_coords(self, mac):
        """Generates deterministic X,Y based on MAC hash."""
        h = hashlib.md5(mac.encode()).hexdigest()
        # Use parts of hash to generate X, Y (-100 to 100)
        x = (int(h[0:4], 16) % 200) - 100
        y = (int(h[4:8], 16) % 200) - 100
        return x, y

    def parse_iw(self, output):
        signals = []
        current = {}
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('BSS '):
                if current: signals.append(current)
                current = {'mac': line.split('(')[0].split()[1], 'encryption': 'Open'}
            elif line.startswith('SSID:'):
                current['ssid'] = line.split(': ')[1]
            elif line.startswith('signal:'):
                current['rssi'] = float(line.split()[1])
            elif line.startswith('freq:'):
                current['freq'] = int(line.split()[1])
            elif 'RSN:' in line:
                current['encryption'] = 'WPA2'
            elif 'WPA:' in line:
                current['encryption'] = 'WPA'
        if current: signals.append(current)
        return signals

    def parse_wpa_cli(self, output):
        signals = []
        lines = output.splitlines()
        if len(lines) < 2: return []
        
        # Skip header
        for line in lines[1:]:
            parts = line.split('\t')
            if len(parts) >= 5:
                signals.append({
                    'mac': parts[0],
                    'freq': int(parts[1]),
                    'rssi': int(parts[2]),
                    'encryption': parts[3],
                    'ssid': parts[4] if len(parts) > 4 else '<HIDDEN>'
                })
        return signals

    def parse_dumpsys(self, output):
        """Parses Android dumpsys wifi output (OneUI variant)."""
        signals = []
        # Pattern for ScanResults in dumpsys
        # Format often varies, looking for common patterns
        # Standard: BSSID|frequency|signal|flags|SSID
        pattern = re.compile(r'([0-9a-fA-F:]{17})\s+(\d+)\s+(-?\d+)\s+\[([^\]]+)\]\s+(.*)')
        
        for line in output.splitlines():
            line = line.strip()
            match = pattern.search(line)
            if match:
                signals.append({
                    'mac': match.group(1),
                    'freq': int(match.group(2)),
                    'rssi': int(match.group(3)),
                    'encryption': match.group(4),
                    'ssid': match.group(5)
                })
        return signals

    def get_demo_data(self):
        """Simulate data for UI testing."""
        import random
        bases = [
            ("Tactical_Ops", -45, "WPA2"),
            ("Free_Wifi", -80, "Open"),
            ("Surveillance_Node", -65, "WEP"),
            ("Unknown_Device", -30, "WPA3"),
            ("Samsung_S24", -55, "WPA2")
        ]
        signals = []
        for name, rssi_base, enc in bases:
            rssi = rssi_base + random.randint(-5, 5)
            signals.append({
                'ssid': name,
                'mac': f"00:11:22:33:44:{random.randint(10,99)}",
                'rssi': rssi,
                'encryption': enc,
                'freq': 2412
            })
        return signals

    def scan(self):
        raw_signals = []
        
        if self.method == "demo":
            raw_signals = self.get_demo_data()
        
        elif self.method == "iw":
            try:
                out = subprocess.check_output(["iw", "dev", self.interface, "scan"], 
                                           timeout=8, encoding='utf-8', errors='ignore')
                raw_signals = self.parse_iw(out)
            except: pass

        elif self.method == "wpa_cli":
            try:
                # Trigger scan
                subprocess.run(["wpa_cli", "-i", self.interface, "scan"], timeout=2)
                time.sleep(1) # Wait for results
                out = subprocess.check_output(["wpa_cli", "-i", self.interface, "scan_results"], 
                                           timeout=5, encoding='utf-8', errors='ignore')
                raw_signals = self.parse_wpa_cli(out)
            except: pass

        elif self.method == "dumpsys":
            try:
                out = subprocess.check_output(["dumpsys", "wifi"], 
                                           timeout=8, encoding='utf-8', errors='ignore')
                raw_signals = self.parse_dumpsys(out)
            except: pass
        
        elif self.method == "proc":
             try:
                with open("/proc/net/wireless", "r") as f:
                    content = f.read()
                    # Minimal parsing for proc
                    if ":" in content:
                        parts = content.splitlines()[2].split()
                        raw_signals = [{
                            'ssid': '<CONNECTED>',
                            'mac': '00:00:00:00:00:00',
                            'rssi': float(parts[3].replace('.', '')),
                            'freq': 2400,
                            'encryption': 'Unknown'
                        }]
             except: pass

        # Process Signals
        processed = []
        for s in raw_signals:
            x, y = self.generate_coords(s.get('mac', ''))
            freq = s.get('freq', 2412)
            rssi = float(s.get('rssi', -100))
            
            p_sig = {
                "type": "wifi",
                "ssid": s.get('ssid', '<HIDDEN>'),
                "mac": s.get('mac', '00:00:00:00:00:00'),
                "rssi": rssi,
                "encryption": s.get('encryption', 'Unknown'),
                "channel": int((freq - 2407) / 5) if freq < 5000 else int((freq - 5000) / 5),
                "distance": self.calculate_distance(rssi, freq),
                "x": x,
                "y": y
            }
            p_sig["risk"] = self.calculate_risk(p_sig)
            processed.append(p_sig)

        return processed

# --- WEB SERVER ---

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>TACTICAL WIFI</title>
    <style>
        :root { --bg: #050505; --grid: #003333; --prim: #00ffff; --warn: #ffff00; --dang: #ff0033; --text: #aaffff; }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { margin: 0; background: var(--bg); color: var(--text); font-family: 'Courier New', monospace; overflow: hidden; height: 100vh; display: flex; flex-direction: column; }
        
        /* HEADER */
        header { height: 50px; border-bottom: 1px solid var(--prim); display: flex; align-items: center; justify-content: space-between; padding: 0 10px; background: rgba(0,20,20,0.9); }
        .status-dot { width: 10px; height: 10px; background: var(--prim); border-radius: 50%; box-shadow: 0 0 10px var(--prim); animation: pulse 2s infinite; }
        .stats { font-size: 12px; display: flex; gap: 10px; }
        
        /* MAIN LAYOUT */
        main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        
        /* MAP */
        #map-container { flex: 1; position: relative; border-bottom: 1px solid var(--grid); overflow: hidden; background: radial-gradient(circle at 50% 50%, #001111 0%, #000000 100%); }
        canvas { width: 100%; height: 100%; display: block; }
        .overlay-info { position: absolute; top: 10px; left: 10px; font-size: 10px; pointer-events: none; opacity: 0.7; }

        /* LIST */
        #signal-list { height: 40%; min-height: 200px; overflow-y: auto; background: rgba(0,0,0,0.9); -webkit-overflow-scrolling: touch; }
        .sig-item { padding: 12px 10px; border-bottom: 1px solid #111; display: flex; justify-content: space-between; align-items: center; border-left: 3px solid transparent; transition: background 0.2s; }
        .sig-item:active { background: #002222; }
        .sig-meta { display: flex; flex-direction: column; gap: 2px; }
        .ssid { font-weight: bold; font-size: 14px; color: #fff; }
        .details { font-size: 11px; opacity: 0.8; }
        .badge { font-size: 10px; padding: 2px 4px; border-radius: 2px; background: #333; }
        
        /* UTILS */
        .risk-high { border-left-color: var(--dang); color: var(--dang); }
        .risk-med { border-left-color: var(--warn); color: var(--warn); }
        .risk-low { border-left-color: var(--prim); color: var(--prim); }
        
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
        
        /* SCROLLBAR */
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-thumb { background: var(--grid); }
    </style>
</head>
<body>
    <header>
        <div style="font-weight:bold;">⬢ TACTICAL</div>
        <div class="stats">
            <span id="scan-method">INIT</span>
            <span>W:<span id="count-wifi">0</span></span>
        </div>
        <div class="status-dot"></div>
    </header>

    <main>
        <div id="map-container">
            <div class="overlay-info">GRID: 10m | TARGET: ACTIVE</div>
            <canvas id="radar"></canvas>
        </div>
        <div id="signal-list">
            <!-- Items injected here -->
        </div>
    </main>

    <script>
        const canvas = document.getElementById('radar');
        const ctx = canvas.getContext('2d');
        const list = document.getElementById('signal-list');
        
        let signals = [];
        let selectedMac = null;
        let scale = 1.0;

        function resize() {
            canvas.width = canvas.parentElement.offsetWidth;
            canvas.height = canvas.parentElement.offsetHeight;
        }
        window.addEventListener('resize', resize);
        resize();

        function drawGrid() {
            const w = canvas.width;
            const h = canvas.height;
            const cx = w/2;
            const cy = h/2;
            
            ctx.fillStyle = '#000';
            ctx.fillRect(0,0,w,h);
            
            // Grid
            ctx.strokeStyle = '#003333';
            ctx.lineWidth = 1;
            ctx.beginPath();
            
            // Circles
            for(let r=50; r<Math.max(w,h); r+=50) {
                ctx.arc(cx, cy, r, 0, Math.PI*2);
            }
            
            // Crosshair
            ctx.moveTo(cx, 0); ctx.lineTo(cx, h);
            ctx.moveTo(0, cy); ctx.lineTo(w, cy);
            ctx.stroke();
        }

        function drawSignals() {
            drawGrid();
            const cx = canvas.width/2;
            const cy = canvas.height/2;
            
            signals.forEach(s => {
                // Map coordinates (-100 to 100) to canvas
                // Scale factor: 2px per unit roughly
                const x = cx + (s.x * 2);
                const y = cy + (s.y * 2);
                
                const isSelected = selectedMac === s.mac;
                
                // Color based on risk
                let color = '#00ffff';
                if(s.risk > 60) color = '#ff0033';
                else if(s.risk > 30) color = '#ffff00';
                
                // Draw Dot
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(x, y, isSelected ? 6 : 3, 0, Math.PI*2);
                ctx.fill();
                
                // Draw Ring
                ctx.strokeStyle = color;
                ctx.beginPath();
                ctx.arc(x, y, isSelected ? 12 : 6, 0, Math.PI*2);
                ctx.stroke();
                
                // Label on hover/select
                if(isSelected) {
                    ctx.fillStyle = '#fff';
                    ctx.font = '10px monospace';
                    ctx.fillText(s.ssid.substring(0,10), x+10, y-10);
                    ctx.fillStyle = '#aaa';
                    ctx.fillText(`${s.rssi}dBm ${s.distance}m`, x+10, y);
                }
            });
        }

        function updateList() {
            const html = signals.map(s => {
                let riskClass = 'risk-low';
                if(s.risk > 60) riskClass = 'risk-high';
                else if(s.risk > 30) riskClass = 'risk-med';
                
                const isSel = selectedMac === s.mac ? 'background: #002222;' : '';

                return `
                <div class="sig-item ${riskClass}" style="${isSel}" onclick="selectSignal('${s.mac}')">
                    <div class="sig-meta">
                        <span class="ssid">${s.ssid}</span>
                        <span class="details">${s.mac} • Ch:${s.channel}</span>
                    </div>
                    <div style="text-align:right">
                        <div class="badge" style="color:${riskClass == 'risk-low' ? '#0ff' : '#f00'}">R:${s.risk}</div>
                        <div class="details" style="margin-top:2px">${s.rssi}dBm</div>
                        <div class="details">${s.distance}m</div>
                    </div>
                </div>`;
            }).join('');
            
            // Only update if length changed or interaction (simple optimization)
            if(list.innerHTML.length !== html.length || selectedMac) {
                list.innerHTML = html;
            }
        }

        window.selectSignal = (mac) => {
            selectedMac = mac;
            drawSignals();
            updateList();
            setTimeout(() => { selectedMac = null; drawSignals(); updateList(); }, 4000);
        };

        // Touch interaction for map
        canvas.addEventListener('touchstart', (e) => {
            const rect = canvas.getBoundingClientRect();
            const tx = e.touches[0].clientX - rect.left;
            const ty = e.touches[0].clientY - rect.top;
            const cx = canvas.width/2;
            const cy = canvas.height/2;

            // Find closest
            let closest = null;
            let minD = 1000;
            
            signals.forEach(s => {
                const sx = cx + (s.x * 2);
                const sy = cy + (s.y * 2);
                const dist = Math.sqrt(Math.pow(sx-tx, 2) + Math.pow(sy-ty, 2));
                if(dist < 30 && dist < minD) {
                    minD = dist;
                    closest = s;
                }
            });
            
            if(closest) selectSignal(closest.mac);
        });

        async function loop() {
            try {
                const res = await fetch('/api/scan');
                const data = await res.json();
                signals = data.signals;
                document.getElementById('count-wifi').innerText = signals.length;
                document.getElementById('scan-method').innerText = data.method.toUpperCase();
                drawSignals();
                if(!selectedMac) updateList();
            } catch(e) { console.error(e); }
            setTimeout(loop, 2000); // 2s polling
        }
        
        loop();
        drawGrid();
    </script>
</body>
</html>
"""

class ScannerHandler(http.server.BaseHTTPRequestHandler):
    scanner = None

    def log_message(self, format, *args):
        return # Silence console logs

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode())
        elif self.path == '/api/scan':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            with data_lock:
                data = {
                    "signals": scan_data["signals"],
                    "method": ScannerHandler.scanner.method,
                    "last_scan": str(datetime.now())
                }
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_background_scan(scanner):
    while True:
        results = scanner.scan()
        with data_lock:
            scan_data["signals"] = sorted(results, key=lambda x: x['rssi'], reverse=True)
            scan_data["last_scan"] = datetime.now()
        
        # Determine sleep based on method (aggressive if demo, slow if iw)
        sleep_time = SCAN_INTERVAL
        time.sleep(sleep_time)

def main():
    print(f"\n⬢ TACTICAL WIFI SCANNER v1.0")
    print(f"⬢ TARGET: http://localhost:{PORT}")
    print("⬢ CTRL+C to Abort\n")

    scanner = AndroidScanner()
    ScannerHandler.scanner = scanner

    # Start Scanner Thread
    t = threading.Thread(target=run_background_scan, args=(scanner,), daemon=True)
    t.start()

    # Start Web Server
    with socketserver.TCPServer(("", PORT), ScannerHandler) as httpd:
        httpd.allow_reuse_address = True
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[!] Shutting down tactical systems...")
            httpd.shutdown()

if __name__ == "__main__":
    main()
