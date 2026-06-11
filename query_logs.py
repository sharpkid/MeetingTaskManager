import sqlite3

conn = sqlite3.connect('wemeet.db')
cur = conn.cursor()

print("=== 会议任务详情 ===")
cur.execute('SELECT meeting_task_id, status, created_at, updated_at FROM meeting_tasks WHERE meeting_task_id LIKE "07a45fb5%"')
rows = cur.fetchall()
for row in rows:
    print(f"任务ID: {row[0]}")
    print(f"状态: {row[1]}")
    print(f"创建时间: {row[2]}")
    print(f"更新时间: {row[3]}")

print("\n=== 挂机任务详情 ===")
cur.execute('SELECT hangup_task_id, status, device_id FROM hangup_tasks WHERE meeting_task_id LIKE "07a45fb5%"')
rows = cur.fetchall()
for row in rows:
    print(f"挂机任务ID: {row[0]}")
    print(f"状态: {row[1]}")
    print(f"设备ID: {row[2]}")

print("\n=== 取消操作日志 ===")
cur.execute('SELECT * FROM api_logs WHERE api_path LIKE "%cancel%" ORDER BY created_at DESC')
rows = cur.fetchall()
for row in rows:
    print(f"时间: {row[8]}")
    print(f"接口: {row[2]}")
    print(f"参数: {row[4]}")
    print(f"结果: {row[5]}")

conn.close()