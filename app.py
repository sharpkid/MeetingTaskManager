from flask import Flask, render_template, request, jsonify
import pymysql
import uuid
from datetime import datetime
import time
import threading
import logging

app = Flask(__name__)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# MySQL数据库配置
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Aw123456'
app.config['MYSQL_DB'] = 'meeting_task_db'

# 心跳配置
HEARTBEAT_INTERVAL = 15  # 心跳周期15秒
HEARTBEAT_TIMEOUT = 3    # 连续3次无心跳判定离线

# 模拟分布式锁（生产环境建议使用Redis）
task_locks = {}

# 请求追踪ID上下文
request_trace_id = None

def get_db():
    conn = pymysql.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB'],
        cursorclass=pymysql.cursors.DictCursor
    )
    return conn

# Trace ID 中间件
@app.before_request
def before_request():
    global request_trace_id
    # 生成唯一的追踪ID
    request_trace_id = str(uuid.uuid4())[:8]  # 使用短UUID便于查看
    
    # 在日志中标记请求开始
    logger.info(f"[TRACE-{request_trace_id}] 请求开始: {request.method} {request.path}")

@app.after_request
def after_request(response):
    global request_trace_id
    # 在日志中标记请求结束
    logger.info(f"[TRACE-{request_trace_id}] 请求结束: {request.method} {request.path} - 状态码: {response.status_code}")
    return response

def init_db():
    conn = get_db()
    try:
        cur = conn.cursor()
        
        # 关闭外键检查
        cur.execute('SET FOREIGN_KEY_CHECKS = 0')
        conn.commit()
        
        # 创建会议任务表（如果不存在）
        cur.execute('''
            CREATE TABLE IF NOT EXISTS meeting_tasks (
                meeting_task_id VARCHAR(36) PRIMARY KEY,
                meeting_code VARCHAR(50) NOT NULL,
                meeting_pwd VARCHAR(20) DEFAULT '',
                start_time DATETIME NOT NULL,
                end_time DATETIME NOT NULL,
                need_num INT NOT NULL DEFAULT 0,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                priority INT NOT NULL DEFAULT 1,
                remark TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        conn.commit()
        
        # 创建挂机任务表（如果不存在）
        cur.execute('''
            CREATE TABLE IF NOT EXISTS hangup_tasks (
                hangup_task_id VARCHAR(36) PRIMARY KEY,
                meeting_task_id VARCHAR(36) NOT NULL,
                device_id VARCHAR(64),
                status VARCHAR(20) NOT NULL DEFAULT 'wait_receive',
                version INT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_meeting_task_id (meeting_task_id),
                INDEX idx_device_id (device_id),
                INDEX idx_status (status),
                INDEX idx_version (version),
                UNIQUE KEY uk_meeting_device (meeting_task_id, device_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        conn.commit()
        
        # 迁移：确保 version 字段存在（兼容旧版本表结构）
        try:
            cur.execute('ALTER TABLE hangup_tasks ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 0')
            conn.commit()
        except Exception:
            pass  # 字段可能已存在
        
        # 创建设备表（如果不存在）
        cur.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                device_id VARCHAR(64) PRIMARY KEY,
                device_model VARCHAR(100) NOT NULL,
                system_version VARCHAR(50) NOT NULL,
                has_tencent_meeting TINYINT NOT NULL DEFAULT 0,
                status VARCHAR(20) NOT NULL DEFAULT 'free',
                last_heartbeat DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                heartbeat_count INT NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        conn.commit()
        
        # 创建设备任务关联表（如果不存在）
        cur.execute('''
            CREATE TABLE IF NOT EXISTS device_task (
                id INT PRIMARY KEY AUTO_INCREMENT,
                device_id VARCHAR(64) NOT NULL,
                hangup_task_id VARCHAR(36) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_device_id (device_id),
                INDEX idx_hangup_task_id (hangup_task_id),
                UNIQUE KEY (device_id, hangup_task_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        conn.commit()
        
        # 创建接口调用日志表（如果不存在）
        cur.execute('''
            CREATE TABLE IF NOT EXISTS api_logs (
                id INT PRIMARY KEY AUTO_INCREMENT,
                trace_id VARCHAR(36),
                device_id VARCHAR(64),
                api_path VARCHAR(100) NOT NULL,
                http_method VARCHAR(10) NOT NULL,
                request_params TEXT,
                response_result TEXT,
                response_code INT,
                ip_address VARCHAR(50),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_device_id (device_id),
                INDEX idx_api_path (api_path),
                INDEX idx_created_at (created_at),
                INDEX idx_trace_id (trace_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        conn.commit()
        
        # 开启外键检查
        cur.execute('SET FOREIGN_KEY_CHECKS = 1')
        conn.commit()
    finally:
        conn.close()

def query_db(query, args=(), one=False):
    conn = get_db()
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute(query, args)
        rv = cur.fetchall()
        return (rv[0] if rv else None) if one else rv
    finally:
        conn.close()

def execute_db(query, args=()):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(query, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def get_current_timestamp():
    return int(time.time())

def datetime_to_timestamp(dt):
    return int(dt.timestamp())

def timestamp_to_datetime(ts):
    return datetime.fromtimestamp(ts)

# ==================== 接口日志记录功能 ====================
import json

def log_api_call(trace_id, device_id, api_path, http_method, request_params, response_result, response_code, ip_address):
    """记录API调用日志到数据库"""
    try:
        # 限制参数和结果长度，避免超出数据库字段限制
        request_params_str = json.dumps(request_params)[:4000] if request_params else None
        response_result_str = json.dumps(response_result)[:4000] if response_result else None
        
        execute_db('''
            INSERT INTO api_logs (trace_id, device_id, api_path, http_method, request_params, response_result, response_code, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (trace_id, device_id, api_path, http_method, request_params_str, response_result_str, response_code, ip_address))
    except Exception as e:
        logger.error(f"[API日志记录失败] {str(e)}")

import functools

def api_logger(f):
    """API调用日志装饰器"""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # 获取请求信息
        api_path = request.path
        http_method = request.method
        ip_address = request.remote_addr
        
        # 获取trace_id
        global request_trace_id
        trace_id = request_trace_id
        
        # 获取请求参数（改进：支持多种格式，避免异常）
        request_params = None
        try:
            if request.method == 'POST':
                # 优先尝试获取JSON
                if request.is_json:
                    try:
                        request_params = request.get_json()
                    except:
                        pass
                
                # 如果不是JSON，尝试获取表单
                if request_params is None:
                    try:
                        if request.form:
                            request_params = dict(request.form)
                    except:
                        pass
                
                # 如果还是没有，尝试获取原始数据
                if request_params is None:
                    try:
                        data = request.get_data(as_text=True)
                        if data:
                            request_params = {'raw_data': data}
                    except:
                        pass
            else:
                request_params = dict(request.args)
        except Exception as e:
            logger.error(f"[API日志获取参数失败] {str(e)}")
            request_params = None
        
        # 获取device_id
        device_id = None
        if request_params:
            device_id = request_params.get('device_id', None)
        
        # 执行原始函数
        response = f(*args, **kwargs)
        
        # 记录日志
        if response:
            try:
                # 解析响应结果
                response_data = None
                if hasattr(response, 'json'):
                    response_data = response.json
                elif isinstance(response, dict):
                    response_data = response
                
                response_code = response_data.get('code', 200) if response_data else 200
                log_api_call(trace_id, device_id, api_path, http_method, request_params, response_data, response_code, ip_address)
            except Exception as e:
                logger.error(f"[API日志解析失败] {str(e)}")
        
        return response
    return decorated_function

# ==================== 客户端接口 ====================

@app.route('/api/client/register', methods=['POST'])
@api_logger
def client_register():
    try:
        device_id = request.form.get('device_id', '').strip()
        device_model = request.form.get('device_model', '').strip()
        system_version = request.form.get('system_version', '').strip()
        has_tencent_meeting = request.form.get('has_tencent_meeting', 'false').lower() == 'true'
        
        logger.info(f"[POST] /api/client/register - device_id={device_id}, device_model={device_model}, system_version={system_version}, has_tencent_meeting={has_tencent_meeting}")
        
        if not device_id:
            return jsonify({'code': 400, 'msg': '设备ID不能为空', 'data': {}})
        if not device_model:
            return jsonify({'code': 400, 'msg': '设备型号不能为空', 'data': {}})
        if not system_version:
            return jsonify({'code': 400, 'msg': '系统版本不能为空', 'data': {}})
        
        # 检查设备是否已注册
        device = query_db('SELECT * FROM devices WHERE device_id = %s', (device_id,), one=True)
        
        if device:
            # 更新设备信息
            execute_db('UPDATE devices SET device_model = %s, system_version = %s, has_tencent_meeting = %s, status = %s, updated_at = CURRENT_TIMESTAMP WHERE device_id = %s',
                       (device_model, system_version, 1 if has_tencent_meeting else 0, 'free', device_id))
            logger.info(f"[设备注册] 设备{device_id}信息已更新")
        else:
            # 新增设备
            execute_db('INSERT INTO devices (device_id, device_model, system_version, has_tencent_meeting, status) VALUES (%s, %s, %s, %s, %s)',
                       (device_id, device_model, system_version, 1 if has_tencent_meeting else 0, 'free'))
            logger.info(f"[设备注册] 设备{device_id}注册成功")
        
        return jsonify({
            'code': 200,
            'msg': '操作成功',
            'data': {
                'is_success': True,
                'device_status': 'free'
            }
        })
    except Exception as e:
        logger.error(f"[设备注册] 异常: {str(e)}")
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

@app.route('/api/client/task/list', methods=['GET'])
@api_logger
def client_task_list():
    try:
        device_id = request.args.get('device_id', '').strip()
        if not device_id:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        # 检查设备是否已注册
        device = query_db('SELECT * FROM devices WHERE device_id = %s', (device_id,), one=True)
        if not device:
            return jsonify({'code': 403, 'msg': '权限拒绝', 'data': {}})
        
        current_time = datetime.now()
        # 获取可领取的挂机任务（关联会议信息）
        # 只有会议已经开始（start_time <= 当前时间）且未结束的任务才能被领取
        tasks = query_db('''
            SELECT ht.hangup_task_id, ht.version, mt.meeting_task_id, mt.meeting_code, mt.meeting_pwd, 
                   mt.start_time, mt.end_time, mt.priority
            FROM hangup_tasks ht
            JOIN meeting_tasks mt ON ht.meeting_task_id = mt.meeting_task_id
            WHERE mt.start_time <= %s  -- 会议已开始
              AND mt.end_time > %s     -- 会议未结束
              AND ht.status = 'wait_receive'
              AND mt.status NOT IN ('canceled', 'completed')
            ORDER BY mt.start_time ASC, mt.created_at ASC
        ''', (current_time, current_time))
        
        result = []
        for task in tasks:
            # 判断任务状态：尚未开始、进行中
            task_status = 'pending'  # 默认尚未开始
            if task['start_time'] <= current_time:
                task_status = 'running'  # 进行中
            
            result.append({
                'hangup_task_id': task['hangup_task_id'],
                'meeting_task_id': task['meeting_task_id'],
                'meeting_code': task['meeting_code'],
                'meeting_pwd': task['meeting_pwd'] or '',
                'start_time': task['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'end_time': task['end_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'priority': task['priority'],
                'version': task['version'],
                'task_status': task_status  # 新增字段：pending(尚未开始)、running(进行中)
            })
        
        return jsonify({
            'code': 200,
            'msg': '操作成功',
            'data': {
                'task_list': result
            }
        })
    except Exception as e:
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

@app.route('/api/client/task/receive', methods=['POST'])
@api_logger
def client_task_receive():
    try:
        device_id = request.form.get('device_id', '').strip()
        hangup_task_id = request.form.get('hangup_task_id', '').strip()
        
        logger.info(f"[POST] /api/client/task/receive - device_id={device_id}, hangup_task_id={hangup_task_id}")
        
        if not device_id:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        if not hangup_task_id:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        # 检查设备状态
        device = query_db('SELECT * FROM devices WHERE device_id = %s', (device_id,), one=True)
        if not device:
            logger.warning(f"[任务领取] 设备{device_id}未注册")
            return jsonify({'code': 403, 'msg': '权限拒绝', 'data': {}})
        
        if device['status'] != 'free':
            logger.warning(f"[任务领取] 设备{device_id}状态非空闲: {device['status']}")
            return jsonify({
                'code': 200,
                'msg': '操作成功',
                'data': {
                    'is_receive_success': False,
                    'fail_reason': '设备忙碌'
                }
            })
        
        # 分布式锁
        lock_key = f'task_lock_{hangup_task_id}'
        if lock_key in task_locks and time.time() - task_locks[lock_key] < 5:
            logger.warning(f"[任务领取] 挂机任务{hangup_task_id}正在处理中")
            return jsonify({
                'code': 200,
                'msg': '操作成功',
                'data': {
                    'is_receive_success': False,
                    'fail_reason': '任务处理中，请稍后重试'
                }
            })
        
        task_locks[lock_key] = time.time()
        
        try:
            # 检查挂机任务状态（关联会议任务）
            task = query_db('''
                SELECT ht.*, mt.meeting_code, mt.meeting_pwd, mt.start_time, mt.end_time, mt.status as meeting_status
                FROM hangup_tasks ht
                JOIN meeting_tasks mt ON ht.meeting_task_id = mt.meeting_task_id
                WHERE ht.hangup_task_id = %s
            ''', (hangup_task_id,), one=True)
            
            if not task:
                logger.warning(f"[任务领取] 挂机任务{hangup_task_id}不存在")
                return jsonify({
                    'code': 200,
                    'msg': '操作成功',
                    'data': {
                        'is_receive_success': False,
                        'fail_reason': '任务不存在'
                    }
                })
            
            current_time = datetime.now()
            if task['end_time'] <= current_time:
                logger.warning(f"[任务领取] 挂机任务{hangup_task_id}已过期")
                return jsonify({
                    'code': 200,
                    'msg': '操作成功',
                    'data': {
                        'is_receive_success': False,
                        'fail_reason': '任务已过期'
                    }
                })
            
            if task['status'] != 'wait_receive':
                logger.warning(f"[任务领取] 挂机任务{hangup_task_id}状态异常: {task['status']}")
                return jsonify({
                    'code': 200,
                    'msg': '操作成功',
                    'data': {
                        'is_receive_success': False,
                        'fail_reason': '任务状态异常'
                    }
                })
            
            if task['meeting_status'] in ('canceled', 'completed'):
                logger.warning(f"[任务领取] 会议任务已取消或完成")
                return jsonify({
                    'code': 200,
                    'msg': '操作成功',
                    'data': {
                        'is_receive_success': False,
                        'fail_reason': '会议已取消'
                    }
                })
            
            # 使用乐观锁更新挂机任务状态
            conn = get_db()
            try:
                cur = conn.cursor()
                
                # 获取任务当前版本号（容错处理）
                task_version = task.get('version', 0)
                if task_version is None:
                    task_version = 0
                
                # 使用 version 进行乐观锁控制
                cur.execute('''
                    UPDATE hangup_tasks 
                    SET status = %s, device_id = %s, version = version + 1, updated_at = CURRENT_TIMESTAMP 
                    WHERE hangup_task_id = %s AND status = %s AND version = %s
                ''', ('running', device_id, hangup_task_id, 'wait_receive', task_version))
                conn.commit()
                
                if cur.rowcount == 0:
                    logger.warning(f"[任务领取] 挂机任务{hangup_task_id}已被其他设备领取或状态已变更")
                    return jsonify({
                        'code': 200,
                        'msg': '操作成功',
                        'data': {
                            'is_receive_success': False,
                            'fail_reason': '任务已被领取'
                        }
                    })
            finally:
                conn.close()
            
            # 同步更新会议任务状态为running（如果还处于pending状态）
            execute_db('UPDATE meeting_tasks SET status = %s WHERE meeting_task_id = %s AND status = %s', 
                       ('running', task['meeting_task_id'], 'pending'))
            
            # 绑定设备任务关系
            execute_db('INSERT INTO device_task (device_id, hangup_task_id) VALUES (%s, %s)', (device_id, hangup_task_id))
            
            # 更新设备状态（同时刷新 last_heartbeat，防止心跳超时检测立即误判为离线）
            execute_db('UPDATE devices SET status = %s, heartbeat_count = 0, last_heartbeat = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE device_id = %s', ('running', device_id))
            
            logger.info(f"[任务领取] 设备{device_id}领取挂机任务{hangup_task_id}成功")
            
            # 获取更新后的版本号（用于后续完成操作）
            updated_task = query_db('SELECT version FROM hangup_tasks WHERE hangup_task_id = %s', (hangup_task_id,), one=True)
            current_version = updated_task['version'] if updated_task else task.get('version', 0) + 1
            
            return jsonify({
                'code': 200,
                'msg': '操作成功',
                'data': {
                    'is_receive_success': True,
                    'fail_reason': '',
                    'task_detail': {
                        'hangup_task_id': hangup_task_id,
                        'meeting_task_id': task['meeting_task_id'],
                        'meeting_code': task['meeting_code'],
                        'meeting_pwd': task['meeting_pwd'] or '',
                        'start_time': task['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
                        'end_time': task['end_time'].strftime('%Y-%m-%d %H:%M:%S'),
                        'version': current_version  # ★ 新增：返回当前版本号，用于完成时的乐观锁验证
                    }
                }
            })
        finally:
            # 释放锁
            if lock_key in task_locks:
                del task_locks[lock_key]
    
    except Exception as e:
        import traceback
        logger.error(f"[任务领取] 异常: {str(e)}")
        logger.error(f"[任务领取] 详细堆栈: {traceback.format_exc()}")
        return jsonify({'code': 500, 'msg': f'服务异常: {str(e)}', 'data': {}})

@app.route('/api/client/heartbeat', methods=['POST'])
@api_logger
def client_heartbeat():
    try:
        device_id = request.form.get('device_id', '').strip()
        device_status = request.form.get('device_status', '').strip()
        current_task_id = request.form.get('current_task_id', '').strip() or None
        in_meeting = request.form.get('in_meeting', 'false').lower() == 'true'
        network_status = request.form.get('network_status', '').strip()
        
        logger.info(f"[心跳上报] device_id={device_id}, status={device_status}, task_id={current_task_id}, in_meeting={in_meeting}, network={network_status}")
        
        if not device_id:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        if not device_status:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        if not network_status:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        device = query_db('SELECT * FROM devices WHERE device_id = %s', (device_id,), one=True)
        if not device:
            logger.warning(f"[心跳上报] 设备{device_id}未注册")
            return jsonify({'code': 403, 'msg': '权限拒绝', 'data': {}})
        
        # 更新心跳信息
        execute_db('UPDATE devices SET status = %s, last_heartbeat = CURRENT_TIMESTAMP, heartbeat_count = 0, updated_at = CURRENT_TIMESTAMP WHERE device_id = %s',
                   (device_status, device_id))
        
        logger.info(f"[心跳上报] 设备{device_id}心跳更新成功")
        
        # 检查任务是否被取消（同时检查挂机任务和会议任务）
        heart_status = 'keep_going'
        task_message = ''
        if current_task_id:
            # 查询挂机任务及其关联的会议任务状态
            task = query_db('''
                SELECT ht.status as hangup_status, mt.status as meeting_status
                FROM hangup_tasks ht
                JOIN meeting_tasks mt ON ht.meeting_task_id = mt.meeting_task_id
                WHERE ht.hangup_task_id = %s
            ''', (current_task_id,), one=True)
            
            if task:
                if task['meeting_status'] == 'canceled':
                    heart_status = 'force_exit'
                    task_message = '会议任务已被取消，请退出会议'
                    logger.warning(f"[心跳上报] 设备{device_id}的任务{current_task_id}对应的会议已被取消")
                elif task['hangup_status'] == 'canceled':
                    heart_status = 'force_exit'
                    task_message = '挂机任务已被取消，请退出会议'
                    logger.warning(f"[心跳上报] 设备{device_id}的任务{current_task_id}已被取消")
        
        return jsonify({
            'code': 200,
            'msg': '操作成功',
            'data': {
                'heart_status': heart_status,
                'server_time': get_current_timestamp(),
                'task_message': task_message
            }
        })
    except Exception as e:
        logger.error(f"[心跳上报] 异常: {str(e)}")
        import traceback
        logger.error(f"[心跳上报] 详细堆栈: {traceback.format_exc()}")
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

@app.route('/api/client/task/report-status', methods=['POST'])
@api_logger
def client_report_status():
    try:
        # 支持多种参数传递方式
        device_id = ''
        hangup_task_id = ''
        in_meeting = False
        version = 0
        
        if request.is_json:
            data = request.get_json()
            device_id = data.get('device_id', '').strip() if data.get('device_id') else ''
            hangup_task_id = data.get('hangup_task_id', '').strip() if data.get('hangup_task_id') else ''
            in_meeting = data.get('in_meeting', False)
            version = data.get('version', 0)
        else:
            device_id = request.form.get('device_id', '').strip()
            hangup_task_id = request.form.get('hangup_task_id', '').strip()
            in_meeting = request.form.get('in_meeting', 'false').lower() == 'true'
            version = int(request.form.get('version', 0))
        
        logger.info(f"[POST] /api/client/task/report-status - device_id={device_id}, hangup_task_id={hangup_task_id}, in_meeting={in_meeting}, version={version}")
        
        if not device_id:
            return jsonify({'code': 400, 'msg': '参数错误：device_id不能为空', 'data': {}})
        if not hangup_task_id:
            return jsonify({'code': 400, 'msg': '参数错误：hangup_task_id不能为空', 'data': {}})
        
        # 检查设备是否注册
        device = query_db('SELECT * FROM devices WHERE device_id = %s', (device_id,), one=True)
        if not device:
            return jsonify({'code': 403, 'msg': '权限拒绝', 'data': {}})
        
        # 获取当前任务状态（包含 version）
        task = query_db('''
            SELECT ht.status, ht.device_id as task_device_id, ht.version, mt.status as meeting_status
            FROM hangup_tasks ht
            LEFT JOIN meeting_tasks mt ON ht.meeting_task_id = mt.meeting_task_id
            WHERE ht.hangup_task_id = %s
        ''', (hangup_task_id,), one=True)
        
        if not task:
            logger.warning(f"[状态上报] 挂机任务{hangup_task_id}不存在")
            return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
        
        # 状态守卫：如果任务已经是 canceled 或 completed，直接返回成功不做处理
        if task['status'] in ('canceled', 'completed'):
            logger.info(f"[状态上报] 任务{hangup_task_id}状态为{task['status']}，无需处理")
            return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
        
        # 状态守卫：如果会议任务已经取消，直接返回成功不做处理
        if task['meeting_status'] == 'canceled':
            logger.info(f"[状态上报] 会议任务已取消，任务{hangup_task_id}无需处理")
            return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
        
        if in_meeting:
            # 入会成功，保持挂机任务运行状态
            # 使用乐观锁验证任务归属
            conn = get_db()
            try:
                cur = conn.cursor()
                # 验证任务当前属于该设备且版本匹配
                cur.execute('''
                    SELECT COUNT(*) as count 
                    FROM hangup_tasks 
                    WHERE hangup_task_id = %s AND device_id = %s AND status = %s AND version = %s
                ''', (hangup_task_id, device_id, 'running', version))
                result = cur.fetchone()
                if result and result['count'] == 0:
                    logger.warning(f"[状态上报] 任务{hangup_task_id}已被回收或分配给其他设备，入会成功上报被忽略")
                    return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
            finally:
                conn.close()
            
            logger.info(f"[状态上报] 设备{device_id}入会成功，挂机任务{hangup_task_id}")
        else:
            # 入会失败，回收挂机任务
            # 状态守卫：只有当前状态是 running 时才允许回收
            if task['status'] != 'running':
                logger.warning(f"[状态上报] 任务{hangup_task_id}当前状态为{task['status']}，不允许回收")
                return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
            
            # 使用乐观锁更新任务状态
            conn = get_db()
            try:
                cur = conn.cursor()
                # 使用 version 和 device_id 进行乐观锁控制
                cur.execute('''
                    UPDATE hangup_tasks 
                    SET status = %s, device_id = NULL, version = version + 1, updated_at = CURRENT_TIMESTAMP 
                    WHERE hangup_task_id = %s AND device_id = %s AND status = %s AND version = %s
                ''', ('wait_receive', hangup_task_id, device_id, 'running', version))
                conn.commit()
                
                if cur.rowcount == 0:
                    logger.warning(f"[状态上报] 任务状态上报被忽略：任务{hangup_task_id}已被回收或分配给其他设备")
                    return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
                
                # 解绑任务
                cur.execute('DELETE FROM device_task WHERE device_task.device_id = %s AND device_task.hangup_task_id = %s', (device_id, hangup_task_id))
                conn.commit()
                
                # 设备置空闲
                cur.execute('UPDATE devices SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE device_id = %s', ('free', device_id))
                conn.commit()
                
                logger.warning(f"[状态上报] 设备{device_id}入会失败，挂机任务{hangup_task_id}已回收")
            finally:
                conn.close()
        
        return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
    except Exception as e:
        logger.error(f"[状态上报] 异常: {str(e)}")
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

@app.route('/api/client/task/complete', methods=['POST'])
@api_logger
def client_task_complete():
    try:
        # 支持多种参数传递方式：JSON Body、Form Body、URL Query Parameters
        device_id = ''
        hangup_task_id = ''
        version = 0
        
        # 优先从 JSON Body 获取
        if request.is_json:
            data = request.get_json()
            device_id = data.get('device_id', '').strip() if data.get('device_id') else ''
            hangup_task_id = data.get('hangup_task_id', '').strip() if data.get('hangup_task_id') else ''
            version = data.get('version', 0)
        
        # 其次从 Form Body 获取
        if not device_id or not hangup_task_id:
            device_id = request.form.get('device_id', '').strip() or device_id
            hangup_task_id = request.form.get('hangup_task_id', '').strip() or hangup_task_id
            version = int(request.form.get('version', 0))
        
        # 最后从 URL 参数获取
        if not device_id or not hangup_task_id:
            device_id = request.args.get('device_id', '').strip() or device_id
            hangup_task_id = request.args.get('hangup_task_id', '').strip() or hangup_task_id
        
        logger.info(f"[POST] /api/client/task/complete - device_id={device_id}, hangup_task_id={hangup_task_id}, version={version}")
        
        if not device_id:
            return jsonify({'code': 400, 'msg': '参数错误：device_id不能为空', 'data': {}})
        if not hangup_task_id:
            return jsonify({'code': 400, 'msg': '参数错误：hangup_task_id不能为空', 'data': {}})
        
        # 使用事务进行原子性操作
        conn = get_db()
        try:
            cur = conn.cursor(pymysql.cursors.DictCursor)
            
            # 获取挂机任务信息（包括状态和版本）
            cur.execute('''
                SELECT meeting_task_id, status, device_id as task_device_id, version 
                FROM hangup_tasks 
                WHERE hangup_task_id = %s
            ''', (hangup_task_id,))
            hangup_task = cur.fetchone()
            
            if not hangup_task:
                logger.warning(f"[任务完成] 挂机任务{hangup_task_id}不存在")
                return jsonify({'code': 404, 'msg': '任务不存在', 'data': {}})
            
            # 检查任务状态是否允许完成
            if hangup_task['status'] == 'completed':
                logger.info(f"[任务完成] 挂机任务{hangup_task_id}已完成，无需重复处理")
                return jsonify({'code': 200, 'msg': '任务已完成', 'data': {}})
            
            if hangup_task['status'] in ('canceled', 'wait_receive'):
                logger.warning(f"[任务完成] 挂机任务{hangup_task_id}状态异常: {hangup_task['status']}")
                return jsonify({'code': 400, 'msg': '任务状态异常', 'data': {}})
            
            # 使用乐观锁验证任务归属
            if hangup_task['task_device_id'] != device_id:
                logger.warning(f"[任务完成] 任务{hangup_task_id}不属于设备{device_id}")
                return jsonify({'code': 400, 'msg': '任务归属异常', 'data': {}})
            
            if hangup_task['version'] != version:
                logger.warning(f"[任务完成] 任务{hangup_task_id}版本不匹配，可能已被其他操作修改")
                return jsonify({'code': 400, 'msg': '任务版本不匹配', 'data': {}})
            
            meeting_task_id = hangup_task['meeting_task_id']
            
            # 使用乐观锁更新挂机任务状态为completed，保留device_id用于统计
            cur.execute('''
                UPDATE hangup_tasks 
                SET status = %s, version = version + 1, updated_at = CURRENT_TIMESTAMP 
                WHERE hangup_task_id = %s AND device_id = %s AND version = %s
            ''', ('completed', hangup_task_id, device_id, version))
            
            if cur.rowcount == 0:
                logger.warning(f"[任务完成] 任务{hangup_task_id}更新失败，可能已被其他设备处理")
                return jsonify({'code': 400, 'msg': '任务更新失败', 'data': {}})
            
            # 解绑设备任务关系
            cur.execute('DELETE FROM device_task WHERE device_task.device_id = %s AND device_task.hangup_task_id = %s', (device_id, hangup_task_id))
            
            # 设备置空闲
            cur.execute('UPDATE devices SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE device_id = %s', ('free', device_id))
            
            # 使用原子性方式检查并更新会议状态
            # 先检查是否所有挂机任务都已完成
            cur.execute('''
                SELECT COUNT(*) as count 
                FROM hangup_tasks 
                WHERE meeting_task_id = %s AND status != %s
            ''', (meeting_task_id, 'completed'))
            remaining_tasks = cur.fetchone()
            
            if remaining_tasks and remaining_tasks['count'] == 0:
                # 所有挂机任务都已完成，更新会议任务状态为completed
                cur.execute('UPDATE meeting_tasks SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE meeting_task_id = %s', 
                           ('completed', meeting_task_id))
                logger.info(f"[任务完成] 会议任务{meeting_task_id}所有挂机任务已完成")
            
            conn.commit()
            logger.info(f"[任务完成] 设备{device_id}完成挂机任务{hangup_task_id}")
            
            return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[任务完成] 异常: {str(e)}")
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

@app.route('/api/client/task/error-exit', methods=['POST'])
@api_logger
def client_error_exit():
    try:
        device_id = request.form.get('device_id', '').strip()
        hangup_task_id = request.form.get('hangup_task_id', '').strip()
        error_msg = request.form.get('error_msg', '').strip()
        
        logger.info(f"[POST] /api/client/task/error-exit - device_id={device_id}, hangup_task_id={hangup_task_id}, error_msg={error_msg}")
        
        if not device_id:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        if not hangup_task_id:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        if not error_msg:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        # 更新挂机任务状态为回收（允许其他设备领取）
        execute_db('UPDATE hangup_tasks SET status = %s, device_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE hangup_task_id = %s', 
                   ('wait_receive', hangup_task_id))
        
        # 解绑设备任务关系
        execute_db('DELETE FROM device_task WHERE device_task.device_id = %s AND device_task.hangup_task_id = %s', (device_id, hangup_task_id))
        
        # 设备置空闲
        execute_db('UPDATE devices SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE device_id = %s', ('free', device_id))
        
        logger.warning(f"[异常退出] 设备{device_id}异常退出，挂机任务{hangup_task_id}已回收，错误: {error_msg}")
        
        return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
    except Exception as e:
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

# ==================== 服务端后台接口 ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/logs')
def logs_page():
    return render_template('logs.html')

@app.route('/api/server/task/publish', methods=['POST'])
def server_publish_task():
    try:
        meeting_code = request.form.get('meeting_code', '').strip()
        meeting_pwd = request.form.get('meeting_pwd', '').strip() or ''
        start_time = request.form.get('start_time', '').strip()
        end_time = request.form.get('end_time', '').strip()
        need_num = request.form.get('need_num', '').strip()
        priority = request.form.get('priority', '1').strip()
        remark = request.form.get('remark', '').strip() or ''
        
        if not meeting_code:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        if not start_time:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        if not end_time:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        if not need_num:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        # ★ 需求1：去除会议号中的"-"字符，支持格式如 "896-982-837"
        meeting_code = meeting_code.replace('-', '')
        
        try:
            start_ts = int(start_time)
            end_ts = int(end_time)
            need_num = int(need_num)
            priority = int(priority)
        except ValueError:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        if need_num < 1:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        current_ts = get_current_timestamp()
        if end_ts <= current_ts:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        if end_ts <= start_ts:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        meeting_task_id = str(uuid.uuid4())
        start_dt = timestamp_to_datetime(start_ts)
        end_dt = timestamp_to_datetime(end_ts)
        
        # 创建会议任务
        execute_db('''
            INSERT INTO meeting_tasks (meeting_task_id, meeting_code, meeting_pwd, start_time, end_time, need_num, status, priority, remark)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (meeting_task_id, meeting_code, meeting_pwd, start_dt, end_dt, need_num, 'pending', priority, remark))
        
        # 创建对应数量的挂机任务
        for _ in range(need_num):
            hangup_task_id = str(uuid.uuid4())
            execute_db('''
                INSERT INTO hangup_tasks (hangup_task_id, meeting_task_id, status)
                VALUES (%s, %s, %s)
            ''', (hangup_task_id, meeting_task_id, 'wait_receive'))
        
        logger.info(f"[会议发布] 会议任务{meeting_task_id}({meeting_code})创建成功，生成{need_num}个挂机任务")
        
        return jsonify({
            'code': 200,
            'msg': '操作成功',
            'data': {
                'meeting_task_id': meeting_task_id,
                'meeting_code': meeting_code,
                'meeting_pwd': meeting_pwd,
                'start_time': start_ts,
                'end_time': end_ts,
                'need_num': need_num,
                'priority': priority,
                'remark': remark
            }
        })
    except Exception as e:
        logger.error(f"[会议发布] 异常: {str(e)}")
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

@app.route('/api/server/task/cancel', methods=['POST'])
def server_cancel_task():
    try:
        meeting_task_id = request.form.get('meeting_task_id', '').strip()
        
        if not meeting_task_id:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        # 检查会议任务是否存在
        meeting_task = query_db('SELECT * FROM meeting_tasks WHERE meeting_task_id = %s', (meeting_task_id,), one=True)
        if not meeting_task:
            return jsonify({'code': 400, 'msg': '参数错误', 'data': {}})
        
        # ★ 需求2：检查会议是否已结束，已过结束时间的任务不能取消
        current_time = datetime.now()
        end_time = meeting_task['end_time']
        if current_time > end_time:
            logger.warning(f"[会议取消] 会议任务{meeting_task_id}({meeting_task['meeting_code']})已结束（结束时间：{end_time}），无法取消")
            return jsonify({'code': 400, 'msg': '会议已结束，无法取消', 'data': {}})
        
        # 获取关联的挂机任务
        hangup_tasks = query_db('SELECT hangup_task_id FROM hangup_tasks WHERE meeting_task_id = %s', (meeting_task_id,))
        
        # 更新会议任务状态为canceled
        execute_db('UPDATE meeting_tasks SET status = %s WHERE meeting_task_id = %s', ('canceled', meeting_task_id))
        
        # 更新所有关联的挂机任务状态为canceled
        for ht in hangup_tasks:
            execute_db('UPDATE hangup_tasks SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE hangup_task_id = %s', 
                       ('canceled', ht['hangup_task_id']))
        
        # 获取关联的设备
        device_tasks = query_db('SELECT dt.device_id, dt.hangup_task_id FROM device_task dt JOIN hangup_tasks ht ON dt.hangup_task_id = ht.hangup_task_id WHERE ht.meeting_task_id = %s', 
                               (meeting_task_id,))
        
        if device_tasks:
            # 解绑所有设备任务关系
            for dt in device_tasks:
                execute_db('DELETE FROM device_task WHERE device_task.device_id = %s AND device_task.hangup_task_id = %s', 
                           (dt['device_id'], dt['hangup_task_id']))
            
            # 所有关联设备置空闲
            for dt in device_tasks:
                execute_db('UPDATE devices SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE device_id = %s', ('free', dt['device_id']))
        
        logger.info(f"[会议取消] 会议任务{meeting_task_id}({meeting_task['meeting_code']})已取消")
        
        return jsonify({'code': 200, 'msg': '操作成功', 'data': {}})
    except Exception as e:
        logger.error(f"[会议取消] 异常: {str(e)}")
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

@app.route('/api/server/stats/device', methods=['GET'])
def server_stats_device():
    try:
        # 总注册设备数
        total_device = query_db('SELECT COUNT(*) as count FROM devices', one=True)['count']
        
        # 在线设备数（心跳时间在3分钟内）
        online_device = query_db('SELECT COUNT(*) as count FROM devices WHERE last_heartbeat > DATE_SUB(NOW(), INTERVAL 3 MINUTE)', one=True)['count']
        
        # 空闲设备数
        free_device = query_db('SELECT COUNT(*) as count FROM devices WHERE status = %s', ('free',), one=True)['count']
        
        # 挂机中设备数
        running_device = query_db('SELECT COUNT(*) as count FROM devices WHERE status = %s', ('running',), one=True)['count']
        
        return jsonify({
            'code': 200,
            'msg': '操作成功',
            'data': {
                'total_device': total_device,
                'online_device': online_device,
                'free_device': free_device,
                'running_device': running_device
            }
        })
    except Exception as e:
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

@app.route('/api/server/stats/task', methods=['GET'])
def server_stats_task():
    try:
        # 总会议任务数
        total_meeting = query_db('SELECT COUNT(*) as count FROM meeting_tasks', one=True)['count']
        
        # 进行中会议任务数
        running_meeting = query_db('SELECT COUNT(*) as count FROM meeting_tasks WHERE status = %s', ('running',), one=True)['count']
        
        # 已完成会议任务数
        completed_meeting = query_db('SELECT COUNT(*) as count FROM meeting_tasks WHERE status = %s', ('completed',), one=True)['count']
        
        # 已取消会议任务数
        canceled_meeting = query_db('SELECT COUNT(*) as count FROM meeting_tasks WHERE status = %s', ('canceled',), one=True)['count']
        
        # 总挂机任务数
        total_hangup = query_db('SELECT COUNT(*) as count FROM hangup_tasks', one=True)['count']
        
        # 待领取挂机任务数
        wait_hangup = query_db('SELECT COUNT(*) as count FROM hangup_tasks WHERE status = %s', ('wait_receive',), one=True)['count']
        
        # 进行中挂机任务数
        running_hangup = query_db('SELECT COUNT(*) as count FROM hangup_tasks WHERE status = %s', ('running',), one=True)['count']
        
        # 已完成挂机任务数
        completed_hangup = query_db('SELECT COUNT(*) as count FROM hangup_tasks WHERE status = %s', ('completed',), one=True)['count']
        
        return jsonify({
            'code': 200,
            'msg': '操作成功',
            'data': {
                'total_meeting': total_meeting,
                'running_meeting': running_meeting,
                'completed_meeting': completed_meeting,
                'canceled_meeting': canceled_meeting,
                'total_hangup': total_hangup,
                'wait_hangup': wait_hangup,
                'running_hangup': running_hangup,
                'completed_hangup': completed_hangup
            }
        })
    except Exception as e:
        logger.error(f"[任务统计] 异常: {str(e)}")
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

# 获取接口调用日志
@app.route('/api/server/logs', methods=['GET'])
def server_get_logs():
    try:
        # 获取参数
        page = int(request.args.get('page', '1'))
        page_size = int(request.args.get('page_size', '20'))
        device_id = request.args.get('device_id', '').strip()
        api_path = request.args.get('api_path', '').strip()
        start_time = request.args.get('start_time', '').strip()
        end_time = request.args.get('end_time', '').strip()
        
        # 计算偏移量
        offset = (page - 1) * page_size
        
        # 构建查询条件
        query = 'SELECT * FROM api_logs WHERE 1=1'
        params = []
        
        if device_id:
            query += ' AND device_id = %s'
            params.append(device_id)
        
        if api_path:
            query += ' AND api_path LIKE %s'
            params.append(f'%{api_path}%')
        
        # 时间范围筛选
        if start_time:
            try:
                # 尝试解析时间戳（秒）
                start_ts = int(start_time)
                start_dt = datetime.fromtimestamp(start_ts)
            except ValueError:
                # 尝试解析日期字符串
                start_dt = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
            query += ' AND created_at >= %s'
            params.append(start_dt)
        
        if end_time:
            try:
                # 尝试解析时间戳（秒）
                end_ts = int(end_time)
                end_dt = datetime.fromtimestamp(end_ts)
            except ValueError:
                # 尝试解析日期字符串
                end_dt = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
            query += ' AND created_at <= %s'
            params.append(end_dt)
        
        query += ' ORDER BY created_at DESC LIMIT %s OFFSET %s'
        params.extend([page_size, offset])
        
        logs = query_db(query, params)
        
        # 获取总数
        count_query = 'SELECT COUNT(*) as count FROM api_logs WHERE 1=1'
        count_params = []
        if device_id:
            count_query += ' AND device_id = %s'
            count_params.append(device_id)
        if api_path:
            count_query += ' AND api_path LIKE %s'
            count_params.append(f'%{api_path}%')
        
        # 时间范围筛选（总数查询）
        if start_time:
            count_query += ' AND created_at >= %s'
            count_params.append(start_dt)
        if end_time:
            count_query += ' AND created_at <= %s'
            count_params.append(end_dt)
        
        total = query_db(count_query, count_params, one=True)['count']
        
        # 格式化日志
        formatted_logs = []
        for log in logs:
            formatted_logs.append({
                'id': log['id'],
                'device_id': log['device_id'] or '-',
                'api_path': log['api_path'],
                'http_method': log['http_method'],
                'request_params': log['request_params'],
                'response_result': log['response_result'],
                'response_code': log['response_code'],
                'ip_address': log['ip_address'],
                'created_at': log['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            })
        
        return jsonify({
            'code': 200,
            'msg': '操作成功',
            'data': {
                'logs': formatted_logs,
                'total': total,
                'page': page,
                'page_size': page_size
            }
        })
    except Exception as e:
        logger.error(f"[日志查询] 异常: {str(e)}")
        return jsonify({'code': 500, 'msg': '服务异常', 'data': {}})

# 添加前端需要的任务列表接口
@app.route('/api/get_tasks', methods=['GET'])
def get_tasks():
    try:
        # 获取会议任务列表，并关联统计挂机任务状态
        tasks = query_db('''
            SELECT mt.*,
                   (SELECT COUNT(*) FROM hangup_tasks ht WHERE ht.meeting_task_id = mt.meeting_task_id) as total_hangup,
                   (SELECT COUNT(*) FROM hangup_tasks ht WHERE ht.meeting_task_id = mt.meeting_task_id AND ht.status = 'wait_receive') as wait_receive,
                   (SELECT COUNT(*) FROM hangup_tasks ht WHERE ht.meeting_task_id = mt.meeting_task_id AND ht.status = 'running') as running,
                   (SELECT COUNT(*) FROM hangup_tasks ht WHERE ht.meeting_task_id = mt.meeting_task_id AND ht.status = 'completed') as completed
            FROM meeting_tasks mt
            ORDER BY mt.start_time ASC, mt.created_at ASC
        ''')
        
        result = []
        for task in tasks:
            result.append({
                'meeting_task_id': task['meeting_task_id'],
                'meeting_code': task['meeting_code'],
                'meeting_pwd': task['meeting_pwd'] or '',
                'start_time': task['start_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'end_time': task['end_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'need_num': task['need_num'],
                'status': task['status'],
                'priority': task['priority'],
                'remark': task['remark'] or '',
                'created_at': task['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
                'total_hangup': task['total_hangup'],
                'wait_receive': task['wait_receive'],
                'running': task['running'],
                'completed': task['completed']
            })
        
        return jsonify({'code': 200, 'msg': '操作成功', 'data': result})
    except Exception as e:
        logger.error(f"[获取任务列表] 异常: {str(e)}")
        return jsonify({'code': 500, 'msg': '服务异常', 'data': []})

# ==================== 定时任务 ====================

def heartbeat_timeout_check():
    """心跳超时检测任务（15秒执行一次）"""
    while True:
        try:
            conn = get_db()
            cur = conn.cursor()
            
            # 使用时间戳差值直接判断超时，而非依赖计数器
            # 查询运行中且心跳超过120秒未更新的设备（增加容错时间，适应USB连接等不稳定场景）
            cur.execute('''
                SELECT device_id 
                FROM devices 
                WHERE status = %s AND TIMESTAMPDIFF(SECOND, last_heartbeat, NOW()) > 120
            ''', ('running',))
            offline_devices = cur.fetchall()
            
            for device in offline_devices:
                device_id = device['device_id']
                
                # 获取设备关联的挂机任务
                cur.execute('SELECT hangup_task_id FROM device_task WHERE device_task.device_id = %s', (device_id,))
                device_tasks = cur.fetchall()
                
                for dt in device_tasks:
                    hangup_task_id = dt['hangup_task_id']
                    # 挂机任务状态改为wait_receive（回收名额，允许其他设备领取）
                    cur.execute('UPDATE hangup_tasks SET status = %s, device_id = NULL, version = version + 1, updated_at = CURRENT_TIMESTAMP WHERE hangup_task_id = %s', 
                               ('wait_receive', hangup_task_id))
                    # 同时回退关联的 meeting_tasks 状态（如果没有其他设备在执行）
                    cur.execute('''
                        UPDATE meeting_tasks mt 
                        JOIN hangup_tasks ht ON mt.meeting_task_id = ht.meeting_task_id
                        SET mt.status = %s 
                        WHERE ht.hangup_task_id = %s 
                        AND NOT EXISTS (
                            SELECT 1 FROM hangup_tasks ht2 
                            WHERE ht2.meeting_task_id = mt.meeting_task_id 
                            AND ht2.status = 'running' 
                            AND ht2.hangup_task_id != %s
                        )
                    ''', ('pending', hangup_task_id, hangup_task_id))
                    logger.warning(f"[心跳超时] 设备{device_id}离线，挂机任务{hangup_task_id}已回收")
                
                # 解绑设备任务关系
                cur.execute('DELETE FROM device_task WHERE device_task.device_id = %s', (device_id,))
                
                # 设备置空闲（重置心跳计数为0）
                cur.execute('UPDATE devices SET status = %s, heartbeat_count = 0 WHERE device_id = %s', ('free', device_id))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f'心跳超时检测异常: {e}')
        
        time.sleep(HEARTBEAT_INTERVAL)

def task_expire_check():
    """任务时间过期检测（1分钟执行一次）"""
    while True:
        try:
            conn = get_db()
            cur = conn.cursor()
            current_time = datetime.now()
            
            # 会议任务过期检测：截止时间已过则自动取消
            cur.execute('SELECT meeting_task_id, meeting_code, end_time FROM meeting_tasks WHERE status = %s AND end_time < NOW()', 
                       ('pending',))
            expired_meetings = cur.fetchall()
            for meeting in expired_meetings:
                logger.warning(f"[会议过期] 会议任务{meeting['meeting_task_id']}({meeting['meeting_code']})截止时间{meeting['end_time']}已过，自动取消")
            
            cur.execute('UPDATE meeting_tasks SET status = %s WHERE status = %s AND end_time < NOW()', 
                       ('canceled', 'pending'))
            
            # 更新所有关联的挂机任务状态为canceled
            cur.execute('SELECT ht.hangup_task_id, mt.meeting_code FROM hangup_tasks ht JOIN meeting_tasks mt ON ht.meeting_task_id = mt.meeting_task_id WHERE mt.status = %s AND ht.status != %s', 
                       ('canceled', 'canceled'))
            hangup_tasks_to_cancel = cur.fetchall()
            for ht in hangup_tasks_to_cancel:
                cur.execute('UPDATE hangup_tasks SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE hangup_task_id = %s', 
                           ('canceled', ht['hangup_task_id']))
                logger.warning(f"[会议过期] 会议{ht['meeting_code']}的挂机任务{ht['hangup_task_id']}已取消")
            
            # 已结束会议任务强制完结
            cur.execute('UPDATE meeting_tasks SET status = %s WHERE status = %s AND end_time < %s', 
                       ('completed', 'running', current_time))
            
            # 释放已结束任务的设备
            cur.execute('SELECT dt.device_id, dt.hangup_task_id FROM device_task dt JOIN hangup_tasks ht ON dt.hangup_task_id = ht.hangup_task_id JOIN meeting_tasks mt ON ht.meeting_task_id = mt.meeting_task_id WHERE mt.status = %s', ('completed',))
            completed_tasks = cur.fetchall()
            
            for ct in completed_tasks:
                cur.execute('UPDATE devices SET status = %s WHERE device_id = %s', ('free', ct['device_id']))
                cur.execute('DELETE FROM device_task WHERE device_task.device_id = %s AND device_task.hangup_task_id = %s', (ct['device_id'], ct['hangup_task_id']))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f'任务过期检测异常: {e}')
        
        time.sleep(60)

def start_scheduled_tasks():
    """启动定时任务"""
    # 心跳超时检测
    heartbeat_thread = threading.Thread(target=heartbeat_timeout_check)
    heartbeat_thread.daemon = True
    heartbeat_thread.start()
    
    # 任务过期检测
    expire_thread = threading.Thread(target=task_expire_check)
    expire_thread.daemon = True
    expire_thread.start()

if __name__ == '__main__':
    init_db()
    start_scheduled_tasks()
    app.run(host='0.0.0.0', port=8080, debug=True)