from flask import Flask, render_template, request, jsonify
import sqlite3
import uuid
from datetime import datetime

app = Flask(__name__)
DATABASE = 'tasks.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    with app.open_resource('schema.sql', mode='r') as f:
        conn.cursor().executescript(f.read())
    conn.commit()
    conn.close()

def query_db(query, args=(), one=False):
    conn = get_db()
    cur = conn.execute(query, args)
    rv = cur.fetchall()
    conn.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    conn = get_db()
    cur = conn.execute(query, args)
    conn.commit()
    conn.close()
    return cur.lastrowid

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/create_task', methods=['POST'])
def create_task():
    try:
        meeting_id = request.form.get('meeting_id', '').strip()
        start_time = request.form.get('start_time', '').strip()
        end_time = request.form.get('end_time', '').strip()
        max_participants = request.form.get('max_participants', '').strip()
        
        if not meeting_id:
            return jsonify({'code': 500, 'msg': '会议号不能为空', 'data': {}})
        if not start_time:
            return jsonify({'code': 500, 'msg': '开始时间不能为空', 'data': {}})
        if not end_time:
            return jsonify({'code': 500, 'msg': '结束时间不能为空', 'data': {}})
        if not max_participants:
            return jsonify({'code': 500, 'msg': '挂机人数上限不能为空', 'data': {}})
        
        try:
            max_participants = int(max_participants)
            if max_participants < 1:
                return jsonify({'code': 500, 'msg': '挂机人数上限必须为正整数', 'data': {}})
        except ValueError:
            return jsonify({'code': 500, 'msg': '挂机人数上限必须为有效数字', 'data': {}})
        
        try:
            start_dt = datetime.strptime(start_time, '%Y-%m-%dT%H:%M')
            end_dt = datetime.strptime(end_time, '%Y-%m-%dT%H:%M')
        except ValueError:
            return jsonify({'code': 500, 'msg': '时间格式不正确', 'data': {}})
        
        current_time = datetime.now()
        
        if end_dt <= current_time:
            return jsonify({'code': 500, 'msg': '会议结束时间不能早于当前时间', 'data': {}})
        
        if end_dt <= start_dt:
            return jsonify({'code': 500, 'msg': '会议结束时间必须晚于开始时间', 'data': {}})
        
        task_id = str(uuid.uuid4())
        execute_db('INSERT INTO tasks (task_id, meeting_id, start_time, end_time, max_participants, current_participants, status) VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (task_id, meeting_id, start_dt.strftime('%Y-%m-%d %H:%M:%S'), end_dt.strftime('%Y-%m-%d %H:%M:%S'), max_participants, 0, 'pending'))
        
        return jsonify({'code': 200, 'msg': '任务创建成功', 'data': {'task_id': task_id}})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e), 'data': {}})

@app.route('/api/get_tasks', methods=['GET'])
def get_tasks():
    try:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        tasks = query_db('SELECT * FROM tasks WHERE end_time > ? ORDER BY created_at DESC', (current_time,))
        
        result = []
        for task in tasks:
            end_dt = datetime.strptime(task['end_time'], '%Y-%m-%d %H:%M:%S')
            start_dt = datetime.strptime(task['start_time'], '%Y-%m-%d %H:%M:%S')
            
            status = task['status']
            if current_time > task['end_time']:
                status = 'ended'
            elif current_time >= task['start_time'] and current_time < task['end_time']:
                status = 'in_progress'
            else:
                status = 'pending'
            
            result.append({
                'task_id': task['task_id'],
                'meeting_id': task['meeting_id'],
                'start_time': task['start_time'],
                'end_time': task['end_time'],
                'max_participants': task['max_participants'],
                'current_participants': task['current_participants'],
                'remaining': task['max_participants'] - task['current_participants'],
                'status': status,
                'start_time_display': start_dt.strftime('%Y-%m-%d %H:%M'),
                'end_time_display': end_dt.strftime('%Y-%m-%d %H:%M')
            })
        
        return jsonify({'code': 200, 'msg': 'success', 'data': result})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e), 'data': {}})

@app.route('/api/delete_task', methods=['POST'])
def delete_task():
    try:
        task_id = request.form.get('taskId', '').strip()
        if not task_id:
            return jsonify({'code': 500, 'msg': '任务ID不能为空', 'data': {}})
        
        task = query_db('SELECT * FROM tasks WHERE task_id = ?', (task_id,), one=True)
        
        if not task:
            return jsonify({'code': 500, 'msg': '任务不存在', 'data': {}})
        
        execute_db('DELETE FROM tasks WHERE task_id = ?', (task_id,))
        
        return jsonify({'code': 200, 'msg': '删除成功', 'data': {}})
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e), 'data': {}})

@app.route('/api/getMeetingTask', methods=['GET', 'POST'])
def get_meeting_task():
    try:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        tasks = query_db('SELECT * FROM tasks WHERE end_time > ? AND current_participants < max_participants ORDER BY start_time ASC, created_at ASC', (current_time,))
        
        if not tasks:
            return jsonify({'code': 500, 'msg': '无可用挂机任务', 'data': {}})
        
        task = tasks[0]
        start_dt = datetime.strptime(task['start_time'], '%Y-%m-%d %H:%M:%S')
        end_dt = datetime.strptime(task['end_time'], '%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            'code': 200,
            'msg': '分配成功',
            'data': {
                'task_id': task['task_id'],
                'meeting_id': task['meeting_id'],
                'start_time': start_dt.strftime('%Y-%m-%d %H:%M'),
                'end_time': end_dt.strftime('%Y-%m-%d %H:%M'),
                'max_participants': task['max_participants'],
                'current_participants': task['current_participants']
            }
        })
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e), 'data': {}})

@app.route('/api/confirmMeetingTask', methods=['POST'])
def confirm_meeting_task():
    try:
        task_id = request.form.get('taskId', '').strip()
        if not task_id:
            return jsonify({'code': 500, 'msg': '任务ID不能为空', 'data': {}})
        
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        task = query_db('SELECT * FROM tasks WHERE task_id = ?', (task_id,), one=True)
        
        if not task:
            return jsonify({'code': 500, 'msg': '任务不存在', 'data': {}})
        
        if task['end_time'] <= current_time:
            return jsonify({'code': 500, 'msg': '任务已结束', 'data': {}})
        
        if task['current_participants'] >= task['max_participants']:
            return jsonify({'code': 500, 'msg': '任务已满', 'data': {}})
        
        execute_db('UPDATE tasks SET current_participants = current_participants + 1 WHERE task_id = ?', (task_id,))
        
        updated_task = query_db('SELECT * FROM tasks WHERE task_id = ?', (task_id,), one=True)
        return jsonify({
            'code': 200,
            'msg': '确认成功',
            'data': {
                'task_id': updated_task['task_id'],
                'current_participants': updated_task['current_participants'],
                'max_participants': updated_task['max_participants'],
                'remaining': updated_task['max_participants'] - updated_task['current_participants']
            }
        })
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e), 'data': {}})

@app.route('/api/quitMeetingTask', methods=['POST'])
def quit_meeting_task():
    try:
        task_id = request.form.get('taskId', '').strip()
        if not task_id:
            return jsonify({'code': 500, 'msg': '任务ID不能为空', 'data': {}})
        
        task = query_db('SELECT * FROM tasks WHERE task_id = ?', (task_id,), one=True)
        
        if not task:
            return jsonify({'code': 500, 'msg': '任务不存在', 'data': {}})
        
        if task['current_participants'] <= 0:
            return jsonify({'code': 500, 'msg': '已挂机人数不能小于0', 'data': {}})
        
        execute_db('UPDATE tasks SET current_participants = current_participants - 1 WHERE task_id = ?', (task_id,))
        
        updated_task = query_db('SELECT * FROM tasks WHERE task_id = ?', (task_id,), one=True)
        return jsonify({
            'code': 200,
            'msg': '退出成功',
            'data': {
                'task_id': updated_task['task_id'],
                'current_participants': updated_task['current_participants'],
                'max_participants': updated_task['max_participants'],
                'remaining': updated_task['max_participants'] - updated_task['current_participants']
            }
        })
    except Exception as e:
        return jsonify({'code': 500, 'msg': str(e), 'data': {}})

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8080, debug=True)