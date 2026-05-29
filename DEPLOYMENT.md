# 腾讯会议挂机任务WEB管理系统 - 部署文档

## 一、服务器环境信息

| 项目 | 信息 |
|------|------|
| 操作系统 | Alibaba Cloud Linux 3 (OpenAnolis Edition) |
| 包管理器 | dnf |
| Python版本 | Python 3.x |
| 服务器IP | 47.85.214.74 |
| 项目路径 | /opt/meeting-task-manager |

## 二、完整部署步骤

### 步骤1：更新系统

```bash
sudo dnf update -y
```

### 步骤2：安装系统依赖

```bash
# 安装Python、Git、Nginx
sudo dnf install -y python3 python3-pip python3-venv git nginx

# 验证安装
python3 --version
git --version
nginx -v
```

### 步骤3：创建项目目录

```bash
sudo mkdir -p /opt/meeting-task-manager
sudo chown -R admin:admin /opt/meeting-task-manager
cd /opt/meeting-task-manager
```

### 步骤4：安装MySQL数据库

```bash
# 安装MySQL服务器
sudo dnf install -y mysql-server

# 启动MySQL服务
sudo systemctl start mysqld

# 设置开机自启
sudo systemctl enable mysqld

# 查看MySQL状态
sudo systemctl status mysqld

# 初始化MySQL（设置root密码）
sudo mysql_secure_installation
```

创建数据库和用户：

```bash
# 登录MySQL
mysql -u root -p

# 创建数据库
CREATE DATABASE meeting_task_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# 创建用户
CREATE USER 'meeting_user'@'localhost' IDENTIFIED BY 'your_secure_password';

# 授权
GRANT ALL PRIVILEGES ON meeting_task_db.* TO 'meeting_user'@'localhost';

# 刷新权限
FLUSH PRIVILEGES;

# 退出
EXIT;
```

### 步骤5：创建Python虚拟环境

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装Python依赖
pip install flask gunicorn
```

### 步骤6：上传项目文件

#### 方法A：使用Git（推荐）

```bash
# 克隆项目代码
git clone <your-git-repo-url> .

# 或如果已有本地仓库
git init
git remote add origin <your-git-repo-url>
git pull origin main
```

#### 方法B：使用SCP（从本地上传）

```bash
# 在本地Windows PowerShell执行
scp -r e:\wemeet\MeetingTaskManager-TRAE\* admin@47.85.214.74:/opt/meeting-task-manager/
```

#### 方法C：手动创建文件

```bash
# 创建目录结构
mkdir -p templates

# 创建app.py文件（复制本地内容）
nano app.py

# 创建前端页面
nano templates/index.html
```

### 步骤7：修改数据库配置

```bash
# 编辑app.py配置MySQL连接信息
nano /opt/meeting-task-manager/app.py

# 修改以下配置（第9-12行）：
# MYSQL_HOST = 'localhost'
# MYSQL_USER = 'meeting_user'
# MYSQL_PASSWORD = 'your_secure_password'  # 设置为您创建数据库时的密码
# MYSQL_DB = 'meeting_task_db'
```

### 步骤8：初始化数据库

```bash
# 确保在项目目录
cd /opt/meeting-task-manager

# 安装MySQL驱动
pip install pymysql

# 初始化数据库（首次运行app.py会自动创建表）
python app.py
```

### 步骤9：启动服务（测试模式）

```bash
# 激活虚拟环境
source venv/bin/activate

# 启动服务（测试）
python app.py

# 访问测试
# http://47.85.214.74:8080
```

### 步骤10：启动服务（生产模式）

```bash
# 使用Gunicorn启动
gunicorn -w 4 -b 0.0.0.0:8080 app:app

# 后台运行
nohup gunicorn -w 4 -b 0.0.0.0:8080 app:app > app.log 2>&1 &

# 查看日志
tail -f app.log
```

### 步骤11：配置Nginx（可选但推荐）

```bash
# 创建Nginx配置文件
sudo nano /etc/nginx/conf.d/meeting-task-manager.conf
```

添加以下配置：

```nginx
server {
    listen 80;
    server_name 47.85.214.74;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启动Nginx：

```bash
# 测试配置
sudo nginx -t

# 启动Nginx
sudo systemctl start nginx

# 设置开机自启
sudo systemctl enable nginx

# 查看状态
sudo systemctl status nginx
```

### 步骤10：配置防火墙

```bash
# 开放HTTP端口
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-port=8080/tcp
sudo firewall-cmd --reload

# 或关闭防火墙（测试用）
sudo systemctl stop firewalld
```

## 三、服务管理命令

### 启动服务

```bash
cd /opt/meeting-task-manager
source venv/bin/activate
nohup gunicorn -w 4 -b 0.0.0.0:8080 app:app > app.log 2>&1 &
```

### 停止服务

```bash
# 查找进程
ps aux | grep gunicorn

# 停止进程
pkill -f gunicorn

# 或使用PID
kill <PID>
```

### 重启服务

```bash
# 停止服务
pkill -f gunicorn

# 启动服务
cd /opt/meeting-task-manager
source venv/bin/activate
nohup gunicorn -w 4 -b 0.0.0.0:8080 app:app > app.log 2>&1 &
```

### 查看日志

```bash
# 实时查看日志
tail -f app.log

# 查看最近100行
tail -n 100 app.log

# 查看错误日志
grep -i error app.log
```

### 查看服务状态

```bash
# 检查端口占用
netstat -tlnp | grep 8080

# 检查进程
ps aux | grep gunicorn

# 测试服务
curl http://localhost:8080/api/get_tasks
```

## 四、创建Systemd服务（推荐）

创建服务文件：

```bash
sudo nano /etc/systemd/system/meeting-task-manager.service
```

添加以下内容：

```ini
[Unit]
Description=Meeting Task Manager
After=network.target

[Service]
Type=notify
User=admin
Group=admin
WorkingDirectory=/opt/meeting-task-manager
Environment="PATH=/opt/meeting-task-manager/venv/bin"
ExecStart=/opt/meeting-task-manager/venv/bin/gunicorn -w 4 -b 0.0.0.0:8080 app:app
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

管理服务：

```bash
# 重新加载systemd配置
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start meeting-task-manager

# 设置开机自启
sudo systemctl enable meeting-task-manager

# 查看状态
sudo systemctl status meeting-task-manager

# 停止服务
sudo systemctl stop meeting-task-manager

# 重启服务
sudo systemctl restart meeting-task-manager

# 查看日志
sudo journalctl -u meeting-task-manager -f
```

## 五、数据库备份

### 备份数据库

```bash
# 备份SQLite数据库
cp meeting_tasks.db meeting_tasks.db.backup.$(date +%Y%m%d_%H%M%S)

# 或创建备份脚本
cat > backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/meeting-task-manager/backups"
mkdir -p $BACKUP_DIR
cp /opt/meeting-task-manager/meeting_tasks.db $BACKUP_DIR/meeting_tasks.db.$(date +%Y%m%d_%H%M%S)
# 保留最近7天的备份
find $BACKUP_DIR -name "meeting_tasks.db.*" -mtime +7 -delete
EOF

chmod +x backup.sh
```

### 设置定时备份

```bash
# 添加定时任务（每天凌晨2点备份）
crontab -e

# 添加以下行
0 2 * * * /opt/meeting-task-manager/backup.sh
```

## 六、访问地址

| 服务 | 地址 |
|------|------|
| 后台管理端 | http://47.85.214.74 |
| 后台管理端（直连） | http://47.85.214.74:8080 |
| 领取任务接口 | http://47.85.214.74/api/getMeetingTask |
| 确认任务接口 | http://47.85.214.74/api/confirmMeetingTask |
| 退出任务接口 | http://47.85.214.74/api/quitMeetingTask |

## 七、常见问题排查

### 问题1：端口被占用

```bash
# 查看端口占用
netstat -tlnp | grep 8080

# 停止占用进程
kill <PID>
```

### 问题2：权限问题

```bash
# 修改文件权限
sudo chown -R admin:admin /opt/meeting-task-manager
chmod +x /opt/meeting-task-manager
```

### 问题3：依赖安装失败

```bash
# 升级pip
pip install --upgrade pip

# 使用国内镜像源
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple flask gunicorn
```

### 问题4：Nginx无法访问

```bash
# 检查Nginx状态
sudo systemctl status nginx

# 检查配置
sudo nginx -t

# 查看错误日志
sudo tail -f /var/log/nginx/error.log
```

## 八、安全建议

1. **修改默认端口**：将SSH端口从22改为其他端口
2. **配置防火墙**：只开放必要的端口
3. **使用HTTPS**：配置SSL证书（Let's Encrypt）
4. **定期备份**：设置自动备份任务
5. **更新系统**：定期执行系统更新
6. **监控日志**：定期检查应用和系统日志

## 九、更新部署

当需要更新代码时：

```bash
cd /opt/meeting-task-manager

# 拉取最新代码
git pull origin main

# 或上传新文件

# 重启服务
sudo systemctl restart meeting-task-manager

# 查看日志确认
sudo journalctl -u meeting-task-manager -f
```

## 十、卸载

```bash
# 停止服务
sudo systemctl stop meeting-task-manager
sudo systemctl disable meeting-task-manager

# 删除服务文件
sudo rm /etc/systemd/system/meeting-task-manager.service
sudo systemctl daemon-reload

# 删除项目目录
sudo rm -rf /opt/meeting-task-manager

# 删除Nginx配置
sudo rm /etc/nginx/conf.d/meeting-task-manager.conf
sudo systemctl restart nginx
```

---

**部署完成时间**: 2026-05-28
**服务器IP**: 47.85.214.74
**部署路径**: /opt/meeting-task-manager