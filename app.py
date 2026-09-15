import os
import sys
import json
import datetime
from flask import Flask, send_from_directory, request, jsonify, session
try:
    from flask_cors import CORS
except ImportError:
    CORS = None

# Force UTF-8 stdout on Windows
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "wos_calc_secret_key_2026")
if CORS:
    CORS(app)

def get_now_utc8():
    """取得台灣 / 台北時間 (UTC+8)"""
    tz_utc8 = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(tz_utc8).strftime("%Y-%m-%d %H:%M:%S")

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
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_settings (
                    key VARCHAR(100) PRIMARY KEY,
                    value TEXT,
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
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
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

def get_admin_password():
    conn, is_pg = get_db()
    cursor = conn.cursor()
    try:
        if is_pg:
            cursor.execute("SELECT value FROM system_settings WHERE key = 'admin_password'")
        else:
            cursor.execute("SELECT value FROM system_settings WHERE key = 'admin_password'")
        row = cursor.fetchone()
        if row:
            val = row[0] if is_pg else row['value']
            if val:
                return str(val).strip()
    except Exception as e:
        print(f"[Admin Pass Query Error] {e}")
    finally:
        cursor.close()
        conn.close()
    return os.environ.get("ADMIN_PASS", "alina5085")

def set_admin_password(new_pwd):
    conn, is_pg = get_db()
    cursor = conn.cursor()
    now_str = get_now_utc8()
    try:
        if is_pg:
            cursor.execute('''
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ('admin_password', %s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at;
            ''', (new_pwd, now_str))
        else:
            cursor.execute('''
                INSERT INTO system_settings (key, value, updated_at)
                VALUES ('admin_password', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
            ''', (new_pwd, now_str))
        conn.commit()
        return True
    except Exception as e:
        print(f"[Admin Pass Set Error] {e}")
        return False
    finally:
        cursor.close()
        conn.close()

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/admin')
@app.route('/admin.html')
def admin_page():
    return send_from_directory('.', 'admin.html')

@app.route('/api/ping', methods=['GET'])
def ping():
    """供 UptimeRobot 等 24 小時定時喚醒 (防休眠)"""
    return jsonify({
        "status": "ok",
        "service": "WOS-Calc",
        "timestamp": get_now_utc8(),
        "timezone": "UTC+8"
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
        now_str = get_now_utc8()

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
def verify_admin(req_data=None):
    current_pass = get_admin_password()
    pwd = None
    if isinstance(req_data, dict):
        pwd = req_data.get('admin_pass') or req_data.get('password')
    if not pwd:
        pwd = request.headers.get('X-Admin-Pass') or session.get('admin_pass') or request.args.get('admin_pass')
    return pwd == current_pass

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    req = request.get_json() or {}
    password = req.get('password', '')
    if password == get_admin_password():
        session['admin_pass'] = password
        return jsonify({"success": True, "msg": "登入成功！"})
    return jsonify({"success": False, "msg": "管理員密碼錯誤"}), 401

@app.route('/api/admin/change-password', methods=['POST'])
def admin_change_password():
    req = request.get_json() or {}
    old_pwd = str(req.get('old_password', '')).strip()
    new_pwd = str(req.get('new_password', '')).strip()
    if not new_pwd:
        return jsonify({"success": False, "msg": "新密碼不能為空"}), 400
    if old_pwd != get_admin_password():
        return jsonify({"success": False, "msg": "舊管理密碼不正確"}), 401
    
    if set_admin_password(new_pwd):
        session['admin_pass'] = new_pwd
        return jsonify({"success": True, "msg": "管理員密碼已成功更新！"})
    return jsonify({"success": False, "msg": "資料庫更新失敗"}), 500

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
        now_str = get_now_utc8()
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

@app.route('/api/admin/backup/export', methods=['GET'])
def admin_backup_export():
    """匯出全資料庫 JSON 備份檔 (包含白名單與所有玩家進度存檔)"""
    if not verify_admin(request.args):
        return jsonify({"success": False, "msg": "無管理員權限"}), 401

    conn, is_pg = get_db()
    cursor = conn.cursor()
    try:
        # 1. 取得白名單
        cursor.execute("SELECT player_id, player_name, note, created_at FROM whitelist ORDER BY created_at ASC")
        wl_rows = cursor.fetchall()
        whitelist_data = []
        for r in wl_rows:
            whitelist_data.append({
                "player_id": r[0] if is_pg else r['player_id'],
                "player_name": r[1] if is_pg else r['player_name'],
                "note": r[2] if is_pg else r['note'],
                "created_at": str(r[3]) if is_pg else str(r['created_at'])
            })

        # 2. 取得玩家進度存檔
        cursor.execute("SELECT player_id, player_name, data_json, updated_at FROM user_saves ORDER BY updated_at ASC")
        save_rows = cursor.fetchall()
        saves_data = []
        for r in save_rows:
            raw_json = r[2] if is_pg else r['data_json']
            try:
                parsed_json = json.loads(raw_json)
            except Exception:
                parsed_json = raw_json
            saves_data.append({
                "player_id": r[0] if is_pg else r['player_id'],
                "player_name": r[1] if is_pg else r['player_name'],
                "data": parsed_json,
                "updated_at": str(r[3]) if is_pg else str(r['updated_at'])
            })

        return jsonify({
            "success": True,
            "backup_version": "1.0",
            "exported_at": get_now_utc8(),
            "timezone": "UTC+8 (Taipei)",
            "total_whitelist": len(whitelist_data),
            "total_saves": len(saves_data),
            "whitelist": whitelist_data,
            "user_saves": saves_data
        })
    except Exception as e:
        return jsonify({"success": False, "msg": f"匯出備份失敗: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/api/admin/backup/import', methods=['POST'])
def admin_backup_import():
    """從 JSON 備份檔還原資料庫 (白名單與進度存檔)"""
    req = request.get_json() or {}
    if not verify_admin(req):
        return jsonify({"success": False, "msg": "無管理員權限"}), 401

    backup = req.get('backup_data', {})
    wl_list = backup.get('whitelist', [])
    save_list = backup.get('user_saves', [])

    if not isinstance(wl_list, list) or not isinstance(save_list, list):
        return jsonify({"success": False, "msg": "備份檔案結構不正確"}), 400

    conn, is_pg = get_db()
    cursor = conn.cursor()
    try:
        now_str = get_now_utc8()
        # 1. 匯入白名單
        for item in wl_list:
            pid = str(item.get('player_id', '')).strip()
            pname = str(item.get('player_name', '')).strip()
            pnote = str(item.get('note', '')).strip()
            pcreated = str(item.get('created_at', '')).strip() or now_str
            if pid:
                if is_pg:
                    cursor.execute('''
                        INSERT INTO whitelist (player_id, player_name, note, created_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (player_id) DO UPDATE SET
                            player_name = EXCLUDED.player_name,
                            note = EXCLUDED.note;
                    ''', (pid, pname, pnote, pcreated))
                else:
                    cursor.execute('''
                        INSERT INTO whitelist (player_id, player_name, note, created_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT (player_id) DO UPDATE SET
                            player_name = excluded.player_name,
                            note = excluded.note;
                    ''', (pid, pname, pnote, pcreated))

        # 2. 匯入進度存檔
        for item in save_list:
            pid = str(item.get('player_id', '')).strip()
            pname = str(item.get('player_name', '')).strip()
            pdata = item.get('data') if item.get('data') is not None else item.get('data_json', {})
            if isinstance(pdata, dict):
                pjson = json.dumps(pdata, ensure_ascii=False)
            else:
                pjson = str(pdata)
            pupdated = str(item.get('updated_at', '')).strip() or now_str
            if pid:
                if is_pg:
                    cursor.execute('''
                        INSERT INTO user_saves (player_id, player_name, data_json, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (player_id) DO UPDATE SET
                            player_name = EXCLUDED.player_name,
                            data_json = EXCLUDED.data_json,
                            updated_at = EXCLUDED.updated_at;
                    ''', (pid, pname, pjson, pupdated))
                else:
                    cursor.execute('''
                        INSERT INTO user_saves (player_id, player_name, data_json, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT (player_id) DO UPDATE SET
                            player_name = excluded.player_name,
                            data_json = excluded.data_json,
                            updated_at = excluded.updated_at;
                    ''', (pid, pname, pjson, pupdated))

        conn.commit()
        return jsonify({
            "success": True,
            "msg": f"資料庫還原成功！已成功匯入 {len(wl_list)} 筆白名單與 {len(save_list)} 筆角色存檔。"
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "msg": f"還原失敗: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print(f"==================================================")
    print(f"[寒霜刺客幫工具] 領主裝備與寶石升級計算機")
    print(f"主頁網址: http://127.0.0.1:{port}")
    print(f"後台網址: http://127.0.0.1:{port}/admin")
    print(f"==================================================")
    app.run(host='0.0.0.0', port=port, debug=False)
