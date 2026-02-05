# 英语朗读评测系统

## 🚀 一键部署（Windows）

### 前置要求
1. 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)
2. 获取 [OpenAI API Key](https://platform.openai.com/api-keys)

### 启动步骤
1. 双击 `启动.bat`
2. 首次运行会提示填入 OpenAI API Key
3. 等待构建完成（首次约 5-10 分钟）
4. 浏览器自动打开 http://localhost

### 常用操作
| 操作 | 方法 |
|------|------|
| 启动服务 | 双击 `启动.bat` |
| 停止服务 | 双击 `停止.bat` |
| 查看日志 | 双击 `查看日志.bat` |

---

## 📁 目录结构
```
├── 启动.bat              # Windows 一键启动
├── 停止.bat              # 停止服务
├── 查看日志.bat          # 查看运行日志
├── docker-compose.yml    # Docker 编排配置
├── Dockerfile.api        # 后端镜像
├── Dockerfile.web        # 前端镜像
├── .env                  # 环境变量（API Key）
├── data/                 # 数据目录（自动创建）
│   ├── uploads/          # 上传的音频
│   └── out/              # 分析结果
└── score_reading/        # 核心评测引擎
```

---

## ⚙️ 配置说明

### 环境变量 (.env)
```env
OPENAI_API_KEY=sk-xxx     # OpenAI API Key（必填）
```

### 端口占用
| 服务 | 端口 | 说明 |
|------|------|------|
| Web | 80 | 前端界面 |
| API | 8000 | 后端接口 |
| Gentle | 8765 | 语音对齐（内部） |

---

## 🔧 故障排除

### Docker 未启动
```
[错误] Docker 未运行
```
→ 打开 Docker Desktop，等待启动完成

### API Key 无效
```
OpenAI API error: Invalid API key
```
→ 编辑 `.env` 文件，检查 API Key 是否正确

### 端口被占用
```
Bind for 0.0.0.0:80 failed: port is already allocated
```
→ 修改 `docker-compose.yml` 中的端口映射，如 `8080:80`

---

## 📞 技术支持
如有问题，请联系开发者。
