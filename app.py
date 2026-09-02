import os
import sys
from flask import Flask, send_from_directory

# Force UTF-8 stdout on Windows
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

app = Flask(__name__, static_folder='.', static_url_path='')

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print(f"==================================================")
    print(f"[寒霜刺客幫工具] 領主裝備與寶石升級計算機")
    print(f"網址: http://127.0.0.1:{port}")
    print(f"==================================================")
    app.run(host='0.0.0.0', port=port, debug=False)
