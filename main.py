#!/usr/bin/env python3
"""
Tactical WiFi Signal Map - Android Termux Edition
Pure Android hardware scanning - No external modules required
Optimized for Samsung OneUI 8 / S24
"""

import json
import time
import math
import threading
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
import subprocess
import os
import sys

class AndroidScanner:
    def __init__(self):
        self.signals = []
        self.timeline = []
        self.lock = threading.Lock()
        self.wifi_working = False
        self.first_scan_done = False
        
    def test_termux_api(self):
        """Test if termux-api is working"""
        try:
            result = subprocess.run(['termux-wifi-scaninfo'], 
                                  capture_output=True, text=True, timeout=5)
            
            # Check if command exists
            if "not found" in result.stderr or "No such file" in result.stderr:
                print("[!] ERROR: termux-api not installed")
                print("[!] Run: pkg install termux-api")
                return False
            
            # Check for permission issues
            if "permission" in result.stderr.lower() or "denied" in result.stderr.lower():
                print("[!] ERROR: Location permission not granted")
                print("[!] Go to Android Settings → Apps → Termux → Permissions → Location → Allow")
                return False
            
            # Check if we got valid output
            if result.stdout and result.stdout.strip():
                try:
                    data = json.loads(result.stdout)
                    if isinstance(data, list):
                        print("[+] Termux API working!")
                        return True
                except:
                    pass
            
            # Empty but no error means WiFi might be off
            if not result.stderr:
                print("[!] WARNING: WiFi scan returned empty - make sure WiFi is ON")
                return True  # API works, just no results
            
            print(f"[!] Unexpected response: {result.stderr[:100]}")
            return False
            
        except FileNotFoundError:
            print("[!] ERROR: termux-api commands not found")
            print("[!] Install with: pkg install termux-api")
            print("[!] Also install Termux:API app from F-Droid")
            return False
        except subprocess.TimeoutExpired:
            print("[!] Scan timeout - but API is installed")
            return True
        except Exception as e:
            print(f"[!] Error testing API: {e}")
            return False
    
    def calculate_distance(self, rssi):
        """Estimate distance from RSSI (in meters)"""
        if rssi == 0 or rssi == -100:
            return 100
        ratio = rssi / -60.0
        if ratio < 1.0:
            return max(0.5, math.pow(ratio, 10))
        return (0.89976) * math.pow(ratio, 7.7095) + 0.111
    
    def calculate_risk_score(self, signal):
        """Calculate security risk score (0-100)"""
        score = 0
        encryption = signal.get('encryption', 'Unknown').upper()
        
        if 'OPEN' in encryption or encryption == '':
            score += 40
        elif 'WEP' in encryption:
            score += 35
        elif 'WPA' in encryption and 'WPA2' not in encryption and 'WPA3' not in encryption:
            score += 20
        
        rssi = signal.get('rssi', -100)
        if rssi > -50:
            score += 30
        elif rssi > -65:
            score += 20
        elif rssi > -75:
            score += 10
        
        ssid = signal.get('ssid', '').lower()
        if any(s in ssid for s in ['free', 'guest', 'public', 'test', 'default']):
            score += 15
        
        if ssid == '' or ssid == '<unknown ssid>':
            score += 20
        
        return min(score, 100)
    
    def scan_wifi(self):
        """Scan WiFi using Termux API"""
        try:
            result = subprocess.run(['termux-wifi-scaninfo'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=8)
            
            if not result.stdout or result.stdout.strip() == "":
                if not self.first_scan_done:
                    print("[!] No WiFi data - checking WiFi is enabled...")
                return []
            
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                if not self.first_scan_done:
                    print("[!] Invalid response from WiFi scan")
                return []
            
            if not isinstance(data, list):
                return []
            
            networks = []
            for network in data:
                ssid = network.get('ssid', '<unknown ssid>')
                bssid = network.get('bssid', 'unknown')
                rssi = network.get('rssi', -100)
                freq = network.get('frequency', 2437)
                caps = network.get('capabilities', '')
                
                # Parse encryption
                if 'WPA3' in caps:
                    enc = 'WPA3'
                elif 'WPA2' in caps:
                    enc = 'WPA2'
                elif 'WPA' in caps:
                    enc = 'WPA'
                elif 'WEP' in caps:
                    enc = 'WEP'
                elif caps == '' or '[ESS]' in caps:
                    enc = 'Open'
                else:
                    enc = 'Unknown'
                
                # Calculate channel
                if freq >= 5000:
                    chan = (freq - 5000) // 5
                else:
                    chan = (freq - 2412) // 5 + 1
                
                networks.append({
                    'type': 'wifi',
                    'ssid': ssid,
                    'mac': bssid,
                    'rssi': rssi,
                    'encryption': enc,
                    'channel': str(chan),
                    'frequency': freq
                })
            
            if not self.first_scan_done and len(networks) > 0:
                print(f"[+] WiFi scanning working! Found {len(networks)} networks")
                self.wifi_working = True
            
            return networks
            
        except subprocess.TimeoutExpired:
            if not self.first_scan_done:
                print("[!] WiFi scan timeout")
            return []
        except Exception as e:
            if not self.first_scan_done:
                print(f"[!] WiFi error: {e}")
            return []
    
    def scan_all(self):
        """Perform full scan"""
        wifi = self.scan_wifi()
        
        all_signals = wifi
        
        # Process signals
        for sig in all_signals:
            sig['distance'] = round(self.calculate_distance(sig['rssi']), 1)
            sig['risk'] = self.calculate_risk_score(sig)
            sig['timestamp'] = datetime.now().isoformat()
            
            # Position based on MAC for consistency
            h = hash(sig['mac'])
            sig['x'] = (h % 180) - 90
            sig['y'] = ((h // 180) % 160) - 80
        
        with self.lock:
            self.signals = all_signals
            self.timeline.insert(0, {
                'time': datetime.now().strftime('%H:%M:%S'),
                'count': len(all_signals),
                'wifi': len(wifi)
            })
            self.timeline = self.timeline[:50]
        
        self.first_scan_done = True
        return all_signals
    
    def get_data(self):
        """Get current signals and timeline"""
        with self.lock:
            return {
                'signals': self.signals,
                'timeline': self.timeline,
                'last_scan': datetime.now().isoformat(),
                'wifi_working': self.wifi_working
            }

class MobileHTTPHandler(SimpleHTTPRequestHandler):
    scanner = None
    
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(self.get_html().encode())
        elif parsed.path == '/api/scan':
            data = self.scanner.get_data()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_error(404)
    
    def get_html(self):
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <title>TACTICAL MAP</title>
    <style>
        * { 
            margin: 0; 
            padding: 0; 
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            background: #000;
            color: #0ff;
            font-family: 'Courier New', monospace;
            overflow: hidden;
            height: 100vh;
            width: 100vw;
            touch-action: pan-y;
        }
        
        #hud {
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            background: #001a1a;
        }
        
        .panel {
            background: rgba(0, 20, 30, 0.95);
            border: 1px solid #0ff;
            box-shadow: 0 0 15px rgba(0, 255, 255, 0.2);
        }
        
        #header {
            padding: 8px 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        
        #logo {
            font-size: 16px;
            font-weight: bold;
            text-shadow: 0 0 10px #0ff;
            letter-spacing: 2px;
        }
        
        #status {
            display: flex;
            gap: 6px;
            font-size: 10px;
        }
        
        .stat {
            padding: 3px 6px;
            background: rgba(0, 255, 255, 0.1);
            border: 1px solid #0ff;
            white-space: nowrap;
        }
        
        #map {
            flex: 1;
            position: relative;
            overflow: hidden;
            margin: 2px;
        }
        
        #map-canvas {
            width: 100%;
            height: 100%;
            border: 2px solid #0ff;
            box-shadow: 0 0 20px rgba(0, 255, 255, 0.3);
        }
        
        #signals-list {
            height: 180px;
            overflow-y: auto;
            overflow-x: hidden;
            font-size: 10px;
            padding: 8px;
            margin: 2px;
            -webkit-overflow-scrolling: touch;
        }
        
        #signals-list::-webkit-scrollbar {
            width: 4px;
        }
        
        #signals-list::-webkit-scrollbar-track {
            background: #001a1a;
        }
        
        #signals-list::-webkit-scrollbar-thumb {
            background: #0ff;
            border-radius: 2px;
        }
        
        .signal-item {
            padding: 6px;
            margin: 3px 0;
            background: rgba(0, 255, 255, 0.05);
            border-left: 3px solid #0ff;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .signal-item:active {
            background: rgba(0, 255, 255, 0.15);
        }
        
        .signal-item.high-risk { border-left-color: #f00; }
        .signal-item.medium-risk { border-left-color: #ff0; }
        
        .signal-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 3px;
            align-items: center;
        }
        
        .signal-name {
            font-weight: bold;
            color: #0ff;
            font-size: 11px;
            word-break: break-all;
            flex: 1;
            margin-right: 6px;
        }
        
        .risk-badge {
            padding: 2px 5px;
            font-size: 8px;
            border-radius: 2px;
            background: #0f0;
            color: #000;
            white-space: nowrap;
        }
        
        .risk-badge.high { background: #f00; color: #fff; }
        .risk-badge.medium { background: #ff0; color: #000; }
        
        .signal-details {
            font-size: 8px;
            opacity: 0.8;
            line-height: 1.3;
        }
        
        .blink {
            animation: blink 1s infinite;
        }
        
        @keyframes blink {
            0%, 50%, 100% { opacity: 1; }
            25%, 75% { opacity: 0.3; }
        }
        
        .list-header {
            font-size: 12px;
            margin-bottom: 6px;
            color: #0ff;
            text-transform: uppercase;
            font-weight: bold;
        }
        
        .error-msg {
            background: rgba(255, 0, 0, 0.2);
            border: 1px solid #f00;
            padding: 8px;
            margin: 8px 0;
            border-radius: 3px;
            font-size: 9px;
            line-height: 1.4;
        }
    </style>
</head>
<body>
    <div id="hud">
        <div id="header" class="panel">
            <div id="logo">⬢ TACTICAL</div>
            <div id="status">
                <div class="stat">WiFi: <span id="wifi-count">0</span></div>
                <div class="stat">Risk: <span id="threat-count">0</span></div>
                <div class="stat blink">●</div>
            </div>
        </div>
        
        <div id="map" class="panel">
            <canvas id="map-canvas"></canvas>
        </div>
        
        <div id="signals-list" class="panel">
            <div class="list-header">⚠ DETECTED SIGNALS</div>
            <div id="signals-container"></div>
        </div>
    </div>
    
    <script>
        const canvas = document.getElementById('map-canvas');
        const ctx = canvas.getContext('2d');
        const mapContainer = document.getElementById('map');
        let signals = [];
        let hoveredSignal = null;
        let scanCount = 0;
        
        function resizeCanvas() {
            const rect = mapContainer.getBoundingClientRect();
            canvas.width = rect.width - 4;
            canvas.height = rect.height - 4;
        }
        
        function drawMap() {
            const w = canvas.width;
            const h = canvas.height;
            
            ctx.fillStyle = '#000';
            ctx.fillRect(0, 0, w, h);
            
            // Grid
            ctx.strokeStyle = 'rgba(0, 255, 255, 0.1)';
            ctx.lineWidth = 0.5;
            const gridSize = Math.min(w, h) / 8;
            
            for (let x = 0; x < w; x += gridSize) {
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, h);
                ctx.stroke();
            }
            
            for (let y = 0; y < h; y += gridSize) {
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
            }
            
            // Center
            const cx = w / 2;
            const cy = h / 2;
            ctx.strokeStyle = '#0ff';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(cx - 12, cy);
            ctx.lineTo(cx + 12, cy);
            ctx.moveTo(cx, cy - 12);
            ctx.lineTo(cx, cy + 12);
            ctx.stroke();
            
            // Signals
            const time = Date.now();
            signals.forEach(sig => {
                const x = cx + (sig.x * (w / 200));
                const y = cy + (sig.y * (h / 200));
                
                // Pulse
                const pulse = 5 + Math.sin(time / 400 + sig.x) * 2;
                ctx.strokeStyle = sig.risk > 60 ? 'rgba(255,0,0,0.5)' : 
                                 sig.risk > 30 ? 'rgba(255,255,0,0.5)' : 
                                 'rgba(0,255,0,0.5)';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.arc(x, y, pulse, 0, Math.PI * 2);
                ctx.stroke();
                
                // Dot
                ctx.fillStyle = sig.risk > 60 ? '#f00' : sig.risk > 30 ? '#ff0' : '#0f0';
                ctx.beginPath();
                ctx.arc(x, y, 3, 0, Math.PI * 2);
                ctx.fill();
                
                // Label
                if (hoveredSignal === sig.mac) {
                    const lw = 100, lh = 35;
                    const lx = Math.max(5, Math.min(x - lw/2, w - lw - 5));
                    const ly = Math.max(5, y - lh - 8);
                    
                    ctx.fillStyle = 'rgba(0,0,0,0.95)';
                    ctx.fillRect(lx, ly, lw, lh);
                    ctx.strokeStyle = '#0ff';
                    ctx.lineWidth = 1;
                    ctx.strokeRect(lx, ly, lw, lh);
                    
                    ctx.fillStyle = '#0ff';
                    ctx.font = '9px Courier New';
                    ctx.textAlign = 'left';
                    ctx.fillText(sig.ssid.substring(0, 14), lx + 4, ly + 11);
                    ctx.fillText(`${sig.rssi}dBm • ${sig.distance}m`, lx + 4, ly + 22);
                    ctx.fillText(sig.encryption, lx + 4, ly + 32);
                }
            });
            
            requestAnimationFrame(drawMap);
        }
        
        function updateSignalsList(data) {
            const container = document.getElementById('signals-container');
            
            if (data.signals.length === 0) {
                container.innerHTML = `
                    <div class="error-msg">
                        <strong>No WiFi networks detected</strong><br><br>
                        ${scanCount < 2 ? 'Initializing scanner...' : 
                        !data.wifi_working ? 
                        'Setup required:<br>1. Enable Location (Android Settings)<br>2. Grant Termux location permission<br>3. Turn WiFi ON<br>4. Run: termux-location' :
                        'WiFi enabled but no networks found'}
                    </div>
                `;
                return;
            }
            
            container.innerHTML = data.signals.map(sig => `
                <div class="signal-item ${sig.risk > 60 ? 'high-risk' : sig.risk > 30 ? 'medium-risk' : ''}" 
                     data-mac="${sig.mac}">
                    <div class="signal-header">
                        <span class="signal-name">${sig.ssid}</span>
                        <span class="risk-badge ${sig.risk > 60 ? 'high' : sig.risk > 30 ? 'medium' : 'low'}">
                            ${sig.risk}
                        </span>
                    </div>
                    <div class="signal-details">
                        ${sig.rssi}dBm • ${sig.distance}m • ${sig.encryption}
                    </div>
                </div>
            `).join('');
            
            document.querySelectorAll('.signal-item').forEach(item => {
                item.addEventListener('click', () => {
                    hoveredSignal = item.dataset.mac;
                    setTimeout(() => { hoveredSignal = null; }, 2000);
                });
            });
        }
        
        async function scan() {
            try {
                const res = await fetch('/api/scan');
                const data = await res.json();
                
                signals = data.signals;
                scanCount++;
                
                document.getElementById('wifi-count').textContent = data.signals.length;
                document.getElementById('threat-count').textContent = 
                    data.signals.filter(s => s.risk > 60).length;
                
                updateSignalsList(data);
            } catch (e) {
                console.error('Scan error:', e);
            }
        }
        
        window.addEventListener('resize', resizeCanvas);
        window.addEventListener('orientationchange', () => setTimeout(resizeCanvas, 100));
        
        resizeCanvas();
        drawMap();
        scan();
        setInterval(scan, 5000);
    </script>
</body>
</html>"""

def run_scanner_loop(scanner):
    """Continuous scanning thread"""
    while True:
        try:
            scanner.scan_all()
            time.sleep(5)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[!] Scanner error: {e}")
            time.sleep(5)

def main():
    print("""
╔════════════════════════════════════════╗
║  TACTICAL MAP - ANDROID TERMUX v2.0   ║
║  WiFi Scanner for Samsung S24 / OneUI  ║
╚════════════════════════════════════════╝
""")
    
    scanner = AndroidScanner()
    
    print("\n[*] Testing Termux API...")
    if not scanner.test_termux_api():
        print("\n[!] SETUP REQUIRED:\n")
        print("1. Install: pkg install termux-api")
        print("2. Install Termux:API app from F-Droid:")
        print("   https://f-droid.org/packages/com.termux.api/")
        print("3. Android Settings → Apps → Termux → Permissions → Location → Allow")
        print("4. Enable Location in Android Settings")
        print("5. Test: termux-location")
        print("\nAfter setup, run this script again.\n")
        sys.exit(1)
    
    MobileHTTPHandler.scanner = scanner
    
    # Start scanner thread
    scanner_thread = threading.Thread(target=run_scanner_loop, args=(scanner,), daemon=True)
    scanner_thread.start()
    
    # Start server
    port = 8080
    server = HTTPServer(('127.0.0.1', port), MobileHTTPHandler)
    
    print(f"\n[+] Server running: http://127.0.0.1:{port}")
    print("[+] Scanning every 5 seconds")
    print("[*] Press Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
        server.shutdown()

if __name__ == '__main__':
    main()
