import urllib.request
import json

for ep in ['/api/sysinfo', '/api/system_info', '/api/devtools/registered', '/api/repair/active-problems']:
    try:
        req = urllib.request.Request(f'http://127.0.0.1:8765{ep}')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f'{ep} -> 200 OK')
            if ep in ('/api/sysinfo', '/api/system_info'):
                print('  cpu_model:', data.get('cpu_model'))
                print('  gpu_model:', data.get('gpu_model'))
                print('  ram_total_gb:', data.get('ram_total_gb'))
            elif ep == '/api/devtools/registered':
                tools = data.get('tools', [])
                print(f'  registered tools count: {len(tools)}')
                for t in tools[:5]:
                    print(f"    - [{t['category']}] {t['name']}")
            elif ep == '/api/repair/active-problems':
                probs = data.get('problems', [])
                print(f'  active problems count: {len(probs)}')
                for p in probs:
                    print(f"    - [{p['source']}] {p['title']} (Risk: {p['risk']}, Auto: {p['auto_implement']})")
    except Exception as e:
        print(f'{ep} -> ERROR: {e}')
