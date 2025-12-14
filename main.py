#!/usr/bin/env python3
"""
Tactical WiFi Signal Map - Android Termux Edition
Uses Android native commands - No Termux API needed
Works on Samsung OneUI 8 / S24
"""

import json
import time
import math
import threading
import re
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
        self.scan_method = None
        
    def find_working_method(self):
        """Find which WiFi scanning method works"""
        print("[*] Finding WiFi scanning method...")
        
        # Method 1: iw (requires root)
        try:
            result = subprocess.run(['su', '-c', 'iw dev wlan0 scan'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and 'BSS' in result.stdout:
                print("[+] Using: iw scan (root)")
                self.scan_method = 'iw'
                return True
        except:
            pass
        
        # Method 2: wpa_cli (common on Android)
        try:
            result = subprocess.run(['su', '-c', 'wpa_cli scan'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                time.sleep(2)
                result = subprocess.run(['su', '-c', 'wpa_cli scan_results'], 
                                      capture_output=True, text=True, timeout=2)
                if 'bssid' in result.stdout.lower():
                    print("[+] Using: wpa_cli (root)")
                    self.scan_method = 'wpa_cli'
                    return True
        except:
            pass
        
        # Method 3: dumpsys (no root needed)
        try:
            result = subprocess.run(['dumpsys', 'wifi'], 
                                  capture_output=True, text=True, timeout=3)
            if 'SSID' in result.stdout or 'bssid' in result.stdout.lower():
                print("[+] Using: dumpsys wifi (no root)")
                self.scan_method = 'dumpsys'
                return True
        except:
            pass
        
        # Method 4: /proc/net/wireless (basic info)
        try:
            with open('/proc/net/wireless', 'r') as f:
                content = f.read()
                if 'wlan' in content:
                    print("[+] Using: /proc/net/wireless (limited)")
                    self.scan_method = 'proc'
                    return True
        except:
            pass
        
        print("[!] No working scan method found")
        return False
    
    def calculate_distance(self, rssi):
        """Estimate distance from RSSI"""
        if rssi == 0 or rssi == -100:
            return 100
        ratio = rssi / -60.0
        if ratio < 1.0:
            return max(0.5, math.pow(ratio, 10))
        return (0.89976) * math.pow(ratio, 7.7095) + 0.111
    
    def calculate_risk_score(self, signal):
        """Calculate risk score"""
        score = 0
        enc = signal.get('encryption', 'Unknown').upper()
        
        if 'OPEN' in enc or enc == '':
            score += 40
        elif 'WEP' in enc:
            score += 35
        elif 'WPA' in enc and 'WPA2' not in enc:
            score += 20
        
        rssi = signal.get('rssi', -100)
        if rssi > -50:
            score += 30
        elif rssi > -65:
            score += 20
        elif rssi > -75:
            score += 10
        
        return min(score, 100)
    
    def scan_iw(self):
        """Scan using iw command"""
        try:
            result = subprocess.run(['su', '-c', 'iw dev wlan0 scan'], 
                                  capture_output=True, text=True, timeout=8)
            
            networks = []
            current = {}
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                
                if line.startswith('BSS'):
                    if current and 'mac' in current:
                        networks.append(current)
                    mac = line.split()[1].rstrip('(on')
                    current = {'mac': mac, 'ssid': '', 'rssi': -80, 'encryption': 'Unknown'}
                    
                elif 'SSID:' in line:
                    current['ssid'] = line.split('SSID:')[1].strip()
                    
                elif 'signal:' in line:
                    try:
                        rssi_str = line.split(':')[1].strip().split()[0]
                        current['rssi'] = int(float(rssi_str))
                    except:
                        pass
                        
                elif 'capability:' in line or 'RSN:' in line or 'WPA:' in line:
                    if 'WPA2' in line or 'RSN' in line:
                        current['encryption'] = 'WPA2'
                    elif 'WPA' in line:
                        current['encryption'] = 'WPA'
                    elif 'Privacy' in line:
                        current['encryption'] = 'WEP'
                    else:
                        current['encryption'] = 'Open'
            
            if current and 'mac' in current:
                networks.append(current)
            
            return self.format_networks(networks)
            
        except Exception as e:
            print(f"[!] iw scan error: {e}")
            return []
    
    def scan_wpa_cli(self):
        """Scan using wpa_cli"""
        try:
            # Trigger scan
            subprocess.run(['su', '-c', 'wpa_cli scan'], 
                         capture_output=True, timeout=2)
            time.sleep(2)
            
            # Get results
            result = subprocess.run(['su', '-c', 'wpa_cli scan_results'], 
                                  capture_output=True, text=True, timeout=3)
            
            networks = []
            for line in result.stdout.split('\n')[1:]:
                parts = line.split('\t')
                if len(parts) >= 5:
                    networks.append({
                        'mac': parts[0],
                        'rssi': int(parts[2]) if parts[2].lstrip('-').isdigit() else -80,
                        'encryption': parts[3] if len(parts) > 3 else 'Unknown',
                        'ssid': parts[4] if len(parts) > 4 else ''
                    })
            
            return self.format_networks(networks)
            
        except Exception as e:
            print(f"[!] wpa_cli scan error: {e}")
            return []
    
    def scan_dumpsys(self):
        """Scan using dumpsys wifi"""
        try:
            result = subprocess.run(['dumpsys', 'wifi'], 
                                  capture_output=True, text=True, timeout=5)
            
            networks = []
            lines = result.stdout.split('\n')
            
            for i, line in enumerate(lines):
                if 'ScanResult' in line or 'SSID:' in line:
                    ssid = ''
                    mac = ''
                    rssi = -80
                    enc = 'Unknown'
                    
                    # Try to extract info from nearby lines
                    for j in range(max(0, i-2), min(len(lines), i+5)):
                        l = lines[j]
                        if 'SSID:' in l or 'ssid:' in l:
                            ssid_match = re.search(r'SSID[:\s]+([^\s,\]]+)', l, re.IGNORECASE)
                            if ssid_match:
                                ssid = ssid_match.group(1).strip('"')
                        if 'BSSID:' in l or 'bssid:' in l:
                            mac_match = re.search(r'([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})', l)
                            if mac_match:
                                mac = mac_match.group(1)
                        if 'level:' in l or 'rssi:' in l:
                            rssi_match = re.search(r'(-?\d+)', l)
                            if rssi_match:
                                rssi = int(rssi_match.group(1))
                        if 'capabilities:' in l.lower() or 'security:' in l.lower():
                            if 'WPA2' in l:
                                enc = 'WPA2'
                            elif 'WPA' in l:
                                enc = 'WPA'
                            elif 'WEP' in l:
                                enc = 'WEP'
                            elif 'OPEN' in l.upper():
                                enc = 'Open'
                    
                    if mac and ssid:
                        networks.append({'mac': mac, 'ssid': ssid, 'rssi': rssi, 'encryption': enc})
            
            # Remove duplicates
            seen = set()
            unique = []
            for net in networks:
                if net['mac'] not in seen:
                    seen.add(net['mac'])
                    unique.append(net)
            
            return self.format_networks(unique)
            
        except Exception as e:
            print(f"[!] dumpsys scan error: {e}")
            return []
    
    def scan_proc(self):
        """Scan using /proc filesystem (very limited)"""
        try:
            # This only gives currently connected network
            with open('/proc/net/wireless', 'r') as f:
                lines = f.readlines()
            
            networks = []
            for line in lines[2:]:  # Skip header
                parts = line.split()
                if len(parts) >= 3:
                    iface = parts[0].rstrip(':')
                    quality = parts[2].rstrip('.')
                    
                    # Try to get current SSID from ip command
                    try:
                        result = subprocess.run(['ip', 'addr', 'show', iface], 
                                              capture_output=True, text=True, timeout=2)
                        # This is very limited - only shows connected network
                        networks.append({
                            'mac': '00:00:00:00:00:00',
                            'ssid': 'Connected Network',
                            'rssi': -70,
                            'encryption': 'Unknown'
                        })
                    except:
                        pass
            
            return self.format_networks(networks)
            
        except:
            return []
    
    def format_networks(self, networks):
        """Format network data"""
        formatted = []
        for net in networks:
            if not net.get('ssid') or not net.get('mac'):
                continue
                
            formatted.append({
                'type': 'wifi',
                'ssid': net['ssid'],
                'mac': net['mac'],
                'rssi': net.get('rssi', -80),
                'encryption': net.get('encryption', 'Unknown'),
                'channel': 'N/A',
                'frequency': 2437
            })
        
        return formatted
    
    def scan_all(self):
        """Perform scan using available method"""
        if not self.scan_method:
            if not self.find_working_method():
                return []
        
        if self.scan_method == 'iw':
            wifi = self.scan_iw()
        elif self.scan_method == 'wpa_cli':
            wifi = self.scan_wpa_cli()
        elif self.scan_method == 'dumpsys':
            wifi = self.scan_dumpsys()
        elif self.scan_method == 'proc':
            wifi = self.scan_proc()
        else:
            wifi = []
        
        # Process signals
        for sig in wifi:
            sig['distance'] = round(self.calculate_distance(sig['rssi']), 1)
            sig['risk'] = self.calculate_risk_score(sig)
            sig['timestamp'] = datetime.now().isoformat()
            h = hash(sig['mac'])
            sig['x'] = (h % 180) - 90
            sig['y'] = ((h // 180) % 160) - 80
        
        with self.lock:
            self.signals = wifi
            self.timeline.insert(0, {
                'time': datetime.now().strftime('%H:%M:%S'),
                'count': len(wifi),
                'wifi': len(wifi)
            })
            self.timeline = self.timeline[:50]
        
        return wifi
    
    def get_data(self):
        """Get current data"""
        with self.lock:
            return {
                'signals': self.signals,
                'timeline': self.timeline,
                'last_scan': datetime.now().isoformat(),
                'method': self.scan_method or 'none'
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
    <title>TACTICAL MAP</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { background: #000; color: #0ff; font-family: 'Courier New', monospace; overflow: hidden; height: 100vh; width: 100vw; }
        #hud { width: 100%; height: 100%; display: flex; flex-direction: column; background: #001a1a; }
        .panel { background: rgba(0, 20, 30, 0.95); border: 1px solid #0ff; box-shadow: 0 0 15px rgba(0, 255, 255, 0.2); }
        #header { padding: 8px 10px; display: flex; justify-content: space-between; align-items: center; }
        #logo { font-size: 16px; font-weight: bold; text-shadow: 0 0 10px #0ff; letter-spacing: 2px; }
        #status { display: flex; gap: 6px; font-size: 10px; }
        .stat { padding: 3px 6px; background: rgba(0, 255, 255, 0.1); border: 1px solid #0ff; white-space: nowrap; }
        #map { flex: 1; position: relative; overflow: hidden; margin: 2px; }
        #map-canvas { width: 100%; height: 100%; border: 2px solid #0ff; box-shadow: 0 0 20px rgba(0, 255, 255, 0.3); }
        #signals-list { height: 180px; overflow-y: auto; font-size: 10px; padding: 8px; margin: 2px; -webkit-overflow-scrolling: touch; }
        .signal-item { padding: 6px; margin: 3px 0; background: rgba(0, 255, 255, 0.05); border-left: 3px solid #0ff; cursor: pointer; }
        .signal-item:active { background: rgba(0, 255, 255, 0.15); }
        .signal-item.high-risk { border-left-color: #f00; }
        .signal-item.medium-risk { border-left-color: #ff0; }
        .signal-header { display: flex; justify-content: space-between; margin-bottom: 3px; }
        .signal-name { font-weight: bold; color: #0ff; font-size: 11px; flex: 1; margin-right: 6px; }
        .risk-badge { padding: 2px 5px; font-size: 8px; border-radius: 2px; background: #0f0; color: #000; }
        .risk-badge.high { background: #f00; color: #fff; }
        .risk-badge.medium { background: #ff0; color: #000; }
        .signal-details { font-size: 8px; opacity: 0.8; }
        .blink { animation: blink 1s infinite; }
        @keyframes blink { 0%, 50%, 100% { opacity: 1; } 25%, 75% { opacity: 0.3; } }
        .list-header { font-size: 12px; margin-bottom: 6px; color: #0ff; text-transform: uppercase; font-weight: bold; }
        .info-msg { background: rgba(0, 255, 255, 0.1); border: 1px solid #0ff; padding: 8px; margin: 8px 0; font-size: 9px; }
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
        <div id="map" class="panel"><canvas id="map-canvas"></canvas></div>
        <div id="signals-list" class="panel">
            <div class="list-header">⚠ SIGNALS</div>
            <div id="signals-container"></div>
        </div>
    </div>
    <script>
        const canvas = document.getElementById('map-canvas');
        const ctx = canvas.getContext('2d');
        const mapContainer = document.getElementById('map');
        let signals = [], hoveredSignal = null, scanCount = 0;
        
        function resizeCanvas() {
            const rect = mapContainer.getBoundingClientRect();
            canvas.width = rect.width - 4;
            canvas.height = rect.height - 4;
        }
        
        function drawMap() {
            const w = canvas.width, h = canvas.height;
            ctx.fillStyle = '#000';
            ctx.fillRect(0, 0, w, h);
            
            ctx.strokeStyle = 'rgba(0, 255, 255, 0.1)';
            ctx.lineWidth = 0.5;
            const gridSize = Math.min(w, h) / 8;
            for (let x = 0; x < w; x += gridSize) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
            for (let y = 0; y < h; y += gridSize) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
            
            const cx = w / 2, cy = h / 2;
            ctx.strokeStyle = '#0ff';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(cx - 12, cy); ctx.lineTo(cx + 12, cy);
            ctx.moveTo(cx, cy - 12); ctx.lineTo(cx, cy + 12);
            ctx.stroke();
            
            const time = Date.now();
            signals.forEach(sig => {
                const x = cx + (sig.x * (w / 200)), y = cy + (sig.y * (h / 200));
                const pulse = 5 + Math.sin(time / 400 + sig.x) * 2;
                ctx.strokeStyle = sig.risk > 60 ? 'rgba(255,0,0,0.5)' : sig.risk > 30 ? 'rgba(255,255,0,0.5)' : 'rgba(0,255,0,0.5)';
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.arc(x, y, pulse, 0, Math.PI * 2);
                ctx.stroke();
                
                ctx.fillStyle = sig.risk > 60 ? '#f00' : sig.risk > 30 ? '#ff0' : '#0f0';
                ctx.beginPath();
                ctx.arc(x, y, 3, 0, Math.PI * 2);
                ctx.fill();
                
                if (hoveredSignal === sig.mac) {
                    const lw = 100, lh = 35, lx = Math.max(5, Math.min(x - lw/2, w - lw - 5)), ly = Math.max(5, y - lh - 8);
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
                container.innerHTML = `<div class="info-msg">Scanning... Method: ${data.method || 'detecting'}<br>Make sure WiFi is enabled</div>`;
                return;
            }
            container.innerHTML = data.signals.map(sig => `
                <div class="signal-item ${sig.risk > 60 ? 'high-risk' : sig.risk > 30 ? 'medium-risk' : ''}" data-mac="${sig.mac}">
                    <div class="signal-header">
                        <span class="signal-name">${sig.ssid}</span>
                        <span class="risk-badge ${sig.risk > 60 ? 'high' : sig.risk > 30 ? 'medium' : 'low'}">${sig.risk}</span>
                    </div>
                    <div class="signal-details">${sig.rssi}dBm • ${sig.distance}m • ${sig.encryption}</div>
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
                document.getElementById('threat-count').textContent = data.signals.filter(s => s.risk > 60).length;
                updateSignalsList(data);
            } catch (e) { console.error('Scan error:', e); }
        }
        
        window.addEventListener('resize', resizeCanvas);
        window.addEventListener('orientationchange', () => setTimeout(resizeCanvas, 100));
        resizeCanvas(); drawMap(); scan(); setInterval(scan, 5000);
    </script>
</body>
</html>"""

def run_scanner_loop(scanner):
    """Continuous scanning"""
    while True:
        try:
            scanner.scan_all()
            time.sleep(5)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[!] Error: {e}")
            time.sleep(5)

def main():
    print("""
╔════════════════════════════════════════╗
║  TACTICAL MAP - NO API REQUIRED v3.0  ║
║  Uses Native Android Commands         ║
╚════════════════════════════════════════╝
""")
    
    scanner = AndroidScanner()
    
    print("\n[*] This script tries multiple scan methods:")
    print("    1. iw (requires root)")
    print("    2. wpa_cli (requires root)")
    print("    3. dumpsys wifi (no root)")
    print("    4. /proc/net/wireless (basic)\n")
    
    MobileHTTPHandler.scanner = scanner
    scanner_thread = threading.Thread(target=run_scanner_loop, args=(scanner,), daemon=True)
    scanner_thread.start()
    
    port = 8080
    server = HTTPServer(('127.0.0.1', port), MobileHTTPHandler)
    
    print(f"[+] Server: http://127.0.0.1:{port}")
    print("[+] Scanning every 5 seconds")
    print("[*] Press Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
        server.shutdown()

if __name__ == '__main__':
    main()
