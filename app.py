import os
import sys
import json
import datetime
from flask import Flask, send_from_directory, request, jsonify, session

# Force UTF-8 stdout on Windows
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "wos_calc_secret_key_2026")

ADMIN_PASS = os.environ.get("ADMIN_PASS", "alina5085")

# ================= 資料庫核心設定 (支援本地 SQLite 與雲端 Supabase PostgreSQL) =================
def get_db():
    db_url = os.environ.get('DATABASE_URL')
    if db_url and (db_url.startswith('postgres://') or db_url.startswith('postgresql://')):
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(db_url)
        return conn, True
    else:
        import sqlite3
        conn = sqlite3.connect('chief.db', timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn, False

def init_db():
    conn, is_pg = get_db()
    cursor = conn.cursor()
    try:
        if is_pg:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whitelist (
                    player_id VARCHAR(100) PRIMARY KEY,
                    player_name VARCHAR(150),
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_saves (
                    player_id VARCHAR(100) PRIMARY KEY,
                    player_name VARCHAR(150),
                    data_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
        else:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whitelist (
                    player_id TEXT PRIMARY KEY,
                    player_name TEXT,
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_saves (
                    player_id TEXT PRIMARY KEY,
                    player_name TEXT,
                    data_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
        conn.commit()
    except Exception as e:
        print(f"[DB Init Error] {e}")
    finally:
        cursor.close()
        conn.close()

# 初始化資料庫表格
init_db()

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/ping', methods=['GET'])
def ping():
    """供 UptimeRobot 等 24 小時定時喚醒 (防休眠)"""
    return jsonify({
        "status": "ok",
        "service": "WOS-Calc",
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route('/api/user', methods=['GET'])
def get_user_data():
    """查詢遊戲 ID 是否在白名單內，若在則一併回傳存檔資料"""
    player_id = request.args.get('player_id', '').strip()
    if not player_id:
        return jsonify({"success": False, "msg": "請輸入遊戲 ID"})

    conn, is_pg = get_db()
    cursor = conn.cursor()
    try:
        # 1. 檢查白名單
        if is_pg:
            cursor.execute("SELECT player_id, player_name, note FROM whitelist WHERE player_id = %s", (player_id,))
        else:
            cursor.execute("SELECT player_id, player_name, note FROM whitelist WHERE player_id = ?", (player_id,))
        
        wl_row = cursor.fetchone()
        if not wl_row:
            return jsonify({
                "success": False,
                "whitelisted": False,
                "msg": "此遊戲 ID 尚未開通存檔權限，請聯絡管理員開通！"
            })

        wl_name = wl_row[1] if is_pg else wl_row['player_name']
        wl_note = wl_row[2] if is_pg else wl_row['note']

        # 2. 抓取存檔資料
        if is_pg:
            cursor.execute("SELECT player_name, data_json, updated_at FROM user_saves WHERE player_id = %s", (player_id,))
        else:
            cursor.execute("SELECT player_name, data_json, updated_at FROM user_saves WHERE player_id = ?", (player_id,))
        
        save_row = cursor.fetchone()
        if save_row:
            p_name = save_row[0] if is_pg else save_row['player_name']
            raw_json = save_row[1] if is_pg else save_row['data_json']
            updated_at = str(save_row[2]) if is_pg else str(save_row['updated_at'])
            try:
                data = json.loads(raw_json)
            except Exception:
                data = {}
            return jsonify({
                "success": True,
                "whitelisted": True,
                "player_id": player_id,
                "player_name": p_name or wl_name,
                "note": wl_note,
                "data": data,
                "updated_at": updated_at,
                "has_save": True,
                "msg": f"歡迎回來 {p_name or wl_name}！已成功載入存檔"
            })
        else:
            return jsonify({
                "success": True,
                "whitelisted": True,
                "player_id": player_id,
                "player_name": wl_name or "",
                "note": wl_note,
                "data": None,
                "has_save": False,
                "msg": f"此 ID 已通過授權！目前尚無存檔紀錄，可點擊「儲存進度」建立首筆存檔。"
            })
    except Exception as e:
        return jsonify({"success": False, "msg": f"伺服器錯誤: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/save', methods=['POST'])
def save_user_data():
    """儲存或更新角色資料 (限白名單內的遊戲 ID)"""
    req = request.get_json() or {}
    player_id = str(req.get('player_id', '')).strip()
    player_name = str(req.get('player_name', '')).strip()
    data = req.get('data', {})

    if not player_id:
        return jsonify({"success": False, "msg": "遊戲 ID 不得為空"}), 400

    conn, is_pg = get_db()
    cursor = conn.cursor()
    try:
        # 1. 驗證白名單
        if is_pg:
            cursor.execute("SELECT player_id, player_name FROM whitelist WHERE player_id = %s", (player_id,))
        else:
            cursor.execute("SELECT player_id, player_name FROM whitelist WHERE player_id = ?", (player_id,))
        
        wl_row = cursor.fetchone()
        if not wl_row:
            return jsonify({"success": False, "msg": "抱歉，此遊戲 ID 未在允許儲存的白名單內！"}), 403

        wl_name = wl_row[1] if is_pg else wl_row['player_name']
        final_player_name = wl_name or player_name or player_id
        data_json = json.dumps(data, ensure_ascii=False)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 2. 寫入存檔 (Upsert)
        if is_pg:
            cursor.execute('''
                INSERT INTO user_saves (player_id, player_name, data_json, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (player_id) DO UPDATE SET
                    player_name = EXCLUDED.player_name,
                    data_json = EXCLUDED.data_json,
                    updated_at = EXCLUDED.updated_at;
            ''', (player_id, final_player_name, data_json, now_str))
        else:
            cursor.execute('''
                INSERT INTO user_saves (player_id, player_name, data_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET
                    player_name = excluded.player_name,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at;
            ''', (player_id, final_player_name, data_json, now_str))
        
        conn.commit()
        return jsonify({
            "success": True,
            "player_name": final_player_name,
            "msg": f"【{final_player_name}】進度已成功儲存至雲端！",
            "updated_at": now_str
        })
    except Exception as e:
        return jsonify({"success": False, "msg": f"儲存失敗: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

# ================= 管理者 API =================
def verify_admin(req_data):
    pwd = req_data.get('admin_pass') or request.headers.get('X-Admin-Pass') or session.get('admin_pass')
    return pwd == ADMIN_PASS

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    req = request.get_json() or {}
    password = req.get('password', '')
    if password == ADMIN_PASS:
        session['admin_pass'] = password
        return jsonify({"success": True, "msg": "登入成功！"})
    return jsonify({"success": False, "msg": "管理員密碼錯誤"}), 401

@app.route('/api/admin/whitelist', methods=['GET'])
def admin_get_whitelist():
    if not verify_admin(request.args):
        return jsonify({"success": False, "msg": "無管理員權限"}), 401

    conn, is_pg = get_db()
    cursor = conn.cursor()
    try:
        sql = '''
            SELECT w.player_id, w.player_name, w.note, w.created_at, s.updated_at,
                   CASE WHEN s.player_id IS NOT NULL THEN 1 ELSE 0 END as has_save
            FROM whitelist w
            LEFT JOIN user_saves s ON w.player_id = s.player_id
            ORDER BY w.created_at DESC
        '''
        cursor.execute(sql)
        rows = cursor.fetchall()
        result = []
        for r in rows:
            if is_pg:
                result.append({
                    "player_id": r[0],
                    "player_name": r[1] or "",
                    "note": r[2] or "",
                    "created_at": str(r[3]),
                    "updated_at": str(r[4]) if r[4] else "",
                    "has_save": bool(r[5])
                })
            else:
                result.append({
                    "player_id": r['player_id'],
                    "player_name": r['player_name'] or "",
                    "note": r['note'] or "",
                    "created_at": str(r['created_at']),
                    "updated_at": str(r['updated_at']) if r['updated_at'] else "",
                    "has_save": bool(r['has_save'])
                })
        return jsonify({"success": True, "whitelist": result})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/admin/whitelist/add', methods=['POST'])
def admin_add_whitelist():
    req = request.get_json() or {}
    if not verify_admin(req):
        return jsonify({"success": False, "msg": "無管理員權限"}), 401

    player_id = str(req.get('player_id', '')).strip()
    player_name = str(req.get('player_name', '')).strip()
    note = str(req.get('note', '')).strip()

    if not player_id:
        return jsonify({"success": False, "msg": "遊戲 ID 不得為空"}), 400

    conn, is_pg = get_db()
    cursor = conn.cursor()
    try:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if is_pg:
            cursor.execute('''
                INSERT INTO whitelist (player_id, player_name, note, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (player_id) DO UPDATE SET
                    player_name = EXCLUDED.player_name,
                    note = EXCLUDED.note;
            ''', (player_id, player_name, note, now_str))
        else:
            cursor.execute('''
                INSERT INTO whitelist (player_id, player_name, note, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (player_id) DO UPDATE SET
                    player_name = excluded.player_name,
                    note = excluded.note;
            ''', (player_id, player_name, note, now_str))
        conn.commit()
        return jsonify({"success": True, "msg": f"已將 ID: {player_id} ({player_name}) 加入白名單！"})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/admin/whitelist/delete', methods=['POST'])
def admin_del_whitelist():
    req = request.get_json() or {}
    if not verify_admin(req):
        return jsonify({"success": False, "msg": "無管理員權限"}), 401

    player_id = str(req.get('player_id', '')).strip()
    if not player_id:
        return jsonify({"success": False, "msg": "遊戲 ID 不得為空"}), 400

    conn, is_pg = get_db()
    cursor = conn.cursor()
    try:
        if is_pg:
            cursor.execute("DELETE FROM whitelist WHERE player_id = %s", (player_id,))
        else:
            cursor.execute("DELETE FROM whitelist WHERE player_id = ?", (player_id,))
        conn.commit()
        return jsonify({"success": True, "msg": f"已從白名單移除 ID: {player_id}"})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print(f"==================================================")
    print(f"[寒霜刺客幫工具] 領主裝備與寶石升級計算機")
    print(f"網址: http://127.0.0.1:{port}")
    print(f"==================================================")
    app.run(host='0.0.0.0', port=port, debug=False)
