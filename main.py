#!/usr/bin/env python3
"""
Tactical WiFi & BLE Signal Map - Android Termux Edition
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

class AndroidScanner:
    def __init__(self):
        self.signals = []
        self.timeline = []
        self.lock = threading.Lock()
        self.debug = True
        self.setup_termux()
        
    def setup_termux(self):
        """Setup Termux API permissions"""
        print("[*] Checking Termux API setup...")
        
        # Check if termux-api package is installed
        try:
            result = subprocess.run(['which', 'termux-wifi-scaninfo'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode != 0:
                print("[!] ERROR: termux-api package not installed")
                print("[!] Run: pkg install termux-api")
                exit(1)
        except Exception as e:
            print(f"[!] Error checking termux-api: {e}")
            exit(1)
        
        # Test WiFi permission
        print("[*] Testing WiFi scanning permission...")
        try:
            result = subprocess.run(['termux-wifi-scaninfo'], 
                                  capture_output=True, text=True, timeout=5)
            if self.debug:
                print(f"[DEBUG] WiFi scan output: {result.stdout[:200]}")
                print(f"[DEBUG] WiFi scan error: {result.stderr[:200]}")
            
            if "permission" in result.stderr.lower():
                print("[!] ERROR: Location permission not granted")
                print("[!] Go to: Settings → Apps → Termux → Permissions")
                print("[!] Enable: Location (Precise)")
                exit(1)
            
            print("[+] Termux API configured correctly")
        except Exception as e:
            print(f"[!] Error: {e}")
            exit(1)
    
    def calculate_distance(self, rssi, frequency=2437):
        """Estimate distance from RSSI (in meters)"""
        if rssi == 0 or rssi == -100:
            return 100
        ratio = rssi / -60.0
        if ratio < 1.0:
            return math.pow(ratio, 10)
        return (0.89976) * math.pow(ratio, 7.7095) + 0.111
    
    def calculate_risk_score(self, signal):
        """Calculate security risk score (0-100)"""
        score = 0
        
        # Encryption weakness
        encryption = signal.get('encryption', 'Unknown')
        if 'OPEN' in encryption.upper() or encryption == '':
            score += 40
        elif 'WEP' in encryption.upper():
            score += 35
        elif 'WPA' in encryption.upper() and 'WPA2' not in encryption.upper():
            score += 20
        
        # Signal strength (closer = riskier for unknown devices)
        rssi = signal.get('rssi', -100)
        if rssi > -50:
            score += 30
        elif rssi > -65:
            score += 20
        elif rssi > -75:
            score += 10
        
        # Unknown/suspicious SSIDs
        ssid = signal.get('ssid', '').lower()
        suspicious = ['free', 'guest', 'public', 'test', 'default', 'android', 'wifi']
        if any(s in ssid for s in suspicious):
            score += 15
        
        # Hidden SSID
        if ssid == '' or ssid == '<unknown ssid>':
            score += 20
        
        return min(score, 100)
    
    def scan_wifi_termux(self):
        """Scan WiFi using Termux API"""
        try:
            # Run the command
            result = subprocess.run(['termux-wifi-scaninfo'], 
                                  capture_output=True, text=True, timeout=10)
            
            if self.debug:
                print(f"[DEBUG] Return code: {result.returncode}")
                print(f"[DEBUG] stdout length: {len(result.stdout)}")
                print(f"[DEBUG] stderr: {result.stderr}")
            
            # Check for errors
            if result.returncode != 0:
                print(f"[!] WiFi scan command failed")
                if "permission" in result.stderr.lower():
                    print("[!] PERMISSION DENIED - Enable Location permission")
                return []
            
            # Handle empty output
            if not result.stdout or result.stdout.strip() == "":
                print("[!] WiFi scan returned empty - checking permissions...")
                print("[!] Make sure:")
                print("    1. Location is ON in Android settings")
                print("    2. Termux has Location permission")
                print("    3. Run: termux-location")
                return []
            
            # Try to parse JSON
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                print(f"[!] Invalid JSON from WiFi scan")
                print(f"[DEBUG] Raw output: {result.stdout[:500]}")
                return []
            
            # Check if data is a list
            if not isinstance(data, list):
                print(f"[!] Unexpected data format: {type(data)}")
                return []
            
            if len(data) == 0:
                print("[!] No WiFi networks found - this is unusual")
                print("[!] Try: termux-wifi-enable")
                return []
            
            networks = []
            
            for network in data:
                ssid = network.get('ssid', '<unknown ssid>')
                bssid = network.get('bssid', 'unknown')
                rssi = network.get('rssi', -100)
                frequency = network.get('frequency', 2437)
                capabilities = network.get('capabilities', '')
                
                # Parse encryption
                if 'WPA2' in capabilities:
                    encryption = 'WPA2'
                elif 'WPA' in capabilities:
                    encryption = 'WPA'
                elif 'WEP' in capabilities:
                    encryption = 'WEP'
                elif capabilities == '' or '[ESS]' == capabilities:
                    encryption = 'Open'
                else:
                    encryption = capabilities
                
                # Calculate channel from frequency
                if frequency >= 5000:
                    channel = str((frequency - 5000) // 5)
                else:
                    channel = str((frequency - 2412) // 5 + 1)
                
                networks.append({
                    'type': 'wifi',
                    'ssid': ssid,
                    'mac': bssid,
                    'rssi': rssi,
                    'encryption': encryption,
                    'channel': channel,
                    'frequency': frequency
                })
            
            return networks
            
        except subprocess.TimeoutExpired:
            print("[!] WiFi scan timeout - trying again...")
            return []
        except Exception as e:
            print(f"[!] WiFi scan error: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return []
    
    def scan_ble_termux(self):
        """Scan BLE using Termux API - currently not available in termux-api"""
        # Note: termux-bluetooth-scaninfo doesn't exist yet
        # We'll skip BLE for now or use alternative methods
        return []
    
    def scan_wifi_alternative(self):
        """Alternative WiFi scan using Android tools"""
        try:
            # Try using iw command if available
            result = subprocess.run(['su', '-c', 'iw dev wlan0 scan'], 
                                  capture_output=True, text=True, timeout=10)
            
            networks = []
            current = {}
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('BSS'):
                    if current:
                        networks.append(current)
                    mac = line.split()[1].rstrip('(on')
                    current = {'mac': mac, 'ssid': '', 'rssi': -100}
                elif 'SSID:' in line:
                    current['ssid'] = line.split('SSID:')[1].strip()
                elif 'signal:' in line:
                    rssi = line.split(':')[1].strip().split()[0]
                    current['rssi'] = float(rssi)
            
            if current:
                networks.append(current)
            
            return networks
        except:
            return []
    
    def scan_all(self):
        """Perform full scan"""
        print("[*] Starting WiFi scan...")
        wifi = self.scan_wifi_termux()
        print(f"[+] Found {len(wifi)} WiFi networks")
        
        # If no results, try alternative
        if len(wifi) == 0:
            print("[*] Trying alternative scan method...")
            wifi = self.scan_wifi_alternative()
            print(f"[+] Alternative found {len(wifi)} networks")
        
        print("[*] BLE scanning not available in current Termux API")
        ble = []
        
        all_signals = wifi + ble
        
        # Process signals
        for sig in all_signals:
            sig['distance'] = round(self.calculate_distance(sig['rssi']), 1)
            sig['risk'] = self.calculate_risk_score(sig)
            sig['timestamp'] = datetime.now().isoformat()
            # Calculate position based on MAC address for consistent placement
            hash_val = hash(sig['mac'])
            sig['x'] = (hash_val % 180) - 90
            sig['y'] = ((hash_val // 180) % 160) - 80
        
        with self.lock:
            self.signals = all_signals
            self.timeline.insert(0, {
                'time': datetime.now().strftime('%H:%M:%S'),
                'count': len(all_signals),
                'wifi': len(wifi),
                'ble': len(ble)
            })
            self.timeline = self.timeline[:50]
        
        return all_signals
    
    def get_data(self):
        """Get current signals and timeline"""
        with self.lock:
            return {
                'signals': self.signals,
                'timeline': self.timeline,
                'last_scan': datetime.now().isoformat()
            }

class MobileHTTPHandler(SimpleHTTPRequestHandler):
    scanner = None
    
    def log_message(self, format, *args):
        """Suppress HTTP logs"""
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
            touch-action: none;
        }
        
        #hud {
            position: relative;
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            background: #001a1a;
        }
        
        .panel {
            background: rgba(0, 20, 30, 0.95);
            border: 1px solid #0ff;
            box-shadow: 0 0 20px rgba(0, 255, 255, 0.3);
        }
        
        #header {
            padding: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        
        #logo {
            font-size: 18px;
            font-weight: bold;
            text-shadow: 0 0 10px #0ff;
            letter-spacing: 2px;
        }
        
        #status {
            display: flex;
            gap: 8px;
            font-size: 11px;
        }
        
        .stat {
            padding: 4px 8px;
            background: rgba(0, 255, 255, 0.1);
            border: 1px solid #0ff;
            white-space: nowrap;
        }
        
        #main-area {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            gap: 2px;
        }
        
        #map {
            flex: 1;
            position: relative;
            overflow: hidden;
            min-height: 300px;
        }
        
        #map-canvas {
            width: 100%;
            height: 100%;
            border: 2px solid #0ff;
            box-shadow: 0 0 30px rgba(0, 255, 255, 0.5);
        }
        
        #signals-list {
            height: 200px;
            overflow-y: auto;
            overflow-x: hidden;
            font-size: 11px;
            padding: 10px;
            -webkit-overflow-scrolling: touch;
        }
        
        #signals-list::-webkit-scrollbar {
            width: 6px;
        }
        
        #signals-list::-webkit-scrollbar-track {
            background: #001a1a;
        }
        
        #signals-list::-webkit-scrollbar-thumb {
            background: #0ff;
            border-radius: 3px;
        }
        
        .signal-item {
            padding: 8px;
            margin: 4px 0;
            background: rgba(0, 255, 255, 0.05);
            border-left: 3px solid #0ff;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .signal-item:active {
            background: rgba(0, 255, 255, 0.2);
        }
        
        .signal-item.high-risk {
            border-left-color: #f00;
        }
        
        .signal-item.medium-risk {
            border-left-color: #ff0;
        }
        
        .signal-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 4px;
            align-items: center;
        }
        
        .signal-name {
            font-weight: bold;
            color: #0ff;
            font-size: 12px;
            word-break: break-all;
            flex: 1;
            margin-right: 8px;
        }
        
        .risk-badge {
            padding: 2px 6px;
            font-size: 9px;
            border-radius: 3px;
            background: #0f0;
            color: #000;
            white-space: nowrap;
            flex-shrink: 0;
        }
        
        .risk-badge.high { background: #f00; color: #fff; }
        .risk-badge.medium { background: #ff0; color: #000; }
        
        .signal-details {
            font-size: 9px;
            opacity: 0.8;
            line-height: 1.4;
        }
        
        .blink {
            animation: blink 1s infinite;
        }
        
        @keyframes blink {
            0%, 50%, 100% { opacity: 1; }
            25%, 75% { opacity: 0.3; }
        }
        
        .list-header {
            font-size: 14px;
            margin-bottom: 8px;
            color: #0ff;
            text-transform: uppercase;
            font-weight: bold;
        }
        
        #loading {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 16px;
            text-align: center;
            z-index: 1000;
            background: rgba(0, 0, 0, 0.9);
            padding: 20px;
            border: 2px solid #0ff;
        }

        .error-msg {
            background: rgba(255, 0, 0, 0.2);
            border: 1px solid #f00;
            padding: 10px;
            margin: 10px;
            border-radius: 5px;
        }
    </style>
</head>
<body>
    <div id="hud">
        <div id="header" class="panel">
            <div id="logo">⬢ TACTICAL</div>
            <div id="status">
                <div class="stat">W:<span id="wifi-count">0</span></div>
                <div class="stat">B:<span id="ble-count">0</span></div>
                <div class="stat">T:<span id="threat-count">0</span></div>
                <div class="stat blink">●</div>
            </div>
        </div>
        
        <div id="main-area">
            <div id="map" class="panel">
                <canvas id="map-canvas"></canvas>
            </div>
            
            <div id="signals-list" class="panel">
                <div class="list-header">⚠ SIGNALS</div>
                <div id="signals-container"></div>
            </div>
        </div>
    </div>
    
    <div id="loading">Initializing...</div>
    
    <script>
        const canvas = document.getElementById('map-canvas');
        const ctx = canvas.getContext('2d');
        const mapContainer = document.getElementById('map');
        const loading = document.getElementById('loading');
        let signals = [];
        let hoveredSignal = null;
        let animFrame = null;
        
        function resizeCanvas() {
            const rect = mapContainer.getBoundingClientRect();
            canvas.width = rect.width - 4;
            canvas.height = rect.height - 4;
            drawMap();
        }
        
        function drawMap() {
            const w = canvas.width;
            const h = canvas.height;
            
            // Clear
            ctx.fillStyle = '#000';
            ctx.fillRect(0, 0, w, h);
            
            // Grid
            ctx.strokeStyle = 'rgba(0, 255, 255, 0.15)';
            ctx.lineWidth = 1;
            
            const gridSize = Math.min(w, h) / 10;
            
            // Vertical lines
            for (let x = 0; x < w; x += gridSize) {
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, h);
                ctx.stroke();
            }
            
            // Horizontal lines
            for (let y = 0; y < h; y += gridSize) {
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
            }
            
            // Center crosshair
            const cx = w / 2;
            const cy = h / 2;
            ctx.strokeStyle = '#0ff';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(cx - 15, cy);
            ctx.lineTo(cx + 15, cy);
            ctx.moveTo(cx, cy - 15);
            ctx.lineTo(cx, cy + 15);
            ctx.stroke();
            
            // Draw signals
            const time = Date.now();
            signals.forEach(sig => {
                const x = cx + (sig.x * (w / 200));
                const y = cy + (sig.y * (h / 200));
                
                // Pulse ring
                const pulseRadius = 6 + Math.sin(time / 300 + sig.x) * 3;
                ctx.strokeStyle = sig.risk > 60 ? 'rgba(255, 0, 0, 0.6)' : 
                                 sig.risk > 30 ? 'rgba(255, 255, 0, 0.6)' : 
                                 'rgba(0, 255, 0, 0.6)';
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.arc(x, y, pulseRadius, 0, Math.PI * 2);
                ctx.stroke();
                
                // Signal point
                ctx.fillStyle = sig.risk > 60 ? '#f00' : sig.risk > 30 ? '#ff0' : '#0f0';
                ctx.beginPath();
                ctx.arc(x, y, 4, 0, Math.PI * 2);
                ctx.fill();
                
                // Label on hover
                if (hoveredSignal === sig.mac) {
                    const labelWidth = 120;
                    const labelHeight = 40;
                    const labelX = Math.max(10, Math.min(x - labelWidth/2, w - labelWidth - 10));
                    const labelY = Math.max(10, y - labelHeight - 10);
                    
                    ctx.fillStyle = 'rgba(0, 0, 0, 0.95)';
                    ctx.fillRect(labelX, labelY, labelWidth, labelHeight);
                    ctx.strokeStyle = '#0ff';
                    ctx.lineWidth = 1;
                    ctx.strokeRect(labelX, labelY, labelWidth, labelHeight);
                    
                    ctx.fillStyle = '#0ff';
                    ctx.font = '10px Courier New';
                    ctx.textAlign = 'left';
                    ctx.fillText(sig.ssid.substring(0, 16), labelX + 5, labelY + 12);
                    ctx.fillText(`${sig.rssi}dBm`, labelX + 5, labelY + 24);
                    ctx.fillText(`${sig.distance}m`, labelX + 5, labelY + 36);
                }
            });
            
            animFrame = requestAnimationFrame(drawMap);
        }
        
        function updateSignalsList(data) {
            const container = document.getElementById('signals-container');
            if (data.signals.length === 0) {
                container.innerHTML = `
                    <div class="error-msg">
                        <strong>No signals detected</strong><br><br>
                        Troubleshooting:<br>
                        1. Enable Location in Android settings<br>
                        2. Grant Termux location permission<br>
                        3. Run: termux-location<br>
                        4. Check WiFi is enabled
                    </div>
                `;
                return;
            }
            
            container.innerHTML = data.signals.map(sig => `
                <div class="signal-item ${sig.risk > 60 ? 'high-risk' : sig.risk > 30 ? 'medium-risk' : ''}" 
                     data-mac="${sig.mac}">
                    <div class="signal-header">
                        <span class="signal-name">${sig.ssid || 'Unknown'}</span>
                        <span class="risk-badge ${sig.risk > 60 ? 'high' : sig.risk > 30 ? 'medium' : 'low'}">
                            ${sig.risk}
                        </span>
                    </div>
                    <div class="signal-details">
                        ${sig.mac}<br>
                        ${sig.rssi}dBm • ${sig.distance}m • ${sig.encryption}
                    </div>
                </div>
            `).join('');
            
            // Add touch handlers
            document.querySelectorAll('.signal-item').forEach(item => {
                item.addEventListener('touchstart', (e) => {
                    hoveredSignal = item.dataset.mac;
                });
                item.addEventListener('touchend', () => {
                    setTimeout(() => { hoveredSignal = null; }, 2000);
                });
            });
        }
        
        async function scan() {
            try {
                const res = await fetch('/api/scan');
                const data = await res.json();
                
                signals = data.signals;
                
                document.getElementById('wifi-count').textContent = data.signals.filter(s => s.type === 'wifi').length;
                document.getElementById('ble-count').textContent = data.signals.filter(s => s.type === 'ble').length;
                document.getElementById('threat-count').textContent = data.signals.filter(s => s.risk > 60).length;
                
                updateSignalsList(data);
                
                if (loading.style.display !== 'none') {
                    loading.style.display = 'none';
                }
            } catch (e) {
                console.error('Scan error:', e);
                loading.textContent = 'Connection error';
            }
        }
        
        window.addEventListener('resize', resizeCanvas);
        window.addEventListener('orientationchange', () => {
            setTimeout(resizeCanvas, 100);
        });
        
        resizeCanvas();
        scan();
        setInterval(scan, 6000);
    </script>
</body>
</html>"""

def run_scanner_loop(scanner):
    """Continuous scanning thread"""
    print("[+] Starting signal scanner loop...")
    while True:
        try:
            scanner.scan_all()
        except Exception as e:
            print(f"[!] Scanner error: {e}")
        time.sleep(6)

def main():
    print("""
╔═══════════════════════════════════════╗
║   TACTICAL MAP - ANDROID EDITION     ║
║   WiFi & BLE Scanner for Termux      ║
║   Samsung OneUI 8 / S24 Optimized    ║
╚═══════════════════════════════════════╝
    """)
    
    print("\n[*] SETUP INSTRUCTIONS:")
    print("1. Install: pkg install termux-api")
    print("2. Install Termux:API app from F-Droid")
    print("3. Enable Location in Android Settings")
    print("4. Grant Termux location permission")
    print("5. Test with: termux-location\n")
    
    scanner = AndroidScanner()
    MobileHTTPHandler.scanner = scanner
    
    # Start scanner thread
    scanner_thread = threading.Thread(target=run_scanner_loop, args=(scanner,), daemon=True)
    scanner_thread.start()
    
    # Start HTTP server
    port = 8080
    server = HTTPServer(('127.0.0.1', port), MobileHTTPHandler)
    
    print(f"\n[+] Server running on port {port}")
    print(f"[+] Open in browser: http://127.0.0.1:{port}")
    print("[+] Scanning every 6 seconds...")
    print("\n[*] Press Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
        server.shutdown()

if __name__ == '__main__':
    main()