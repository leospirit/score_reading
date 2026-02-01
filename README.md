# 口语评分 CLI 框架

朗读/背诵口语评分命令行工具。支持 MP3 输入、100 分制评分、逐词高亮 HTML 报告、发音修改建议生成。

## 功能特性

- ✅ **多引擎支持**：auto/fast/standard/pro 四种模式，自动选择最优引擎
- ✅ **失败回退**：引擎失败或漏词过多时自动回退到备用引擎
- ✅ **四维评分**：发音准确度、流利度、语调、完整度
- ✅ **逐词高亮**：HTML 报告中按评分着色显示每个词
- ✅ **发音建议**：基于音素规则库生成针对性练习建议
- ✅ **批量处理**：支持 CSV manifest 批量评分

## 快速开始

### 环境要求

- Python >= 3.10
- ffmpeg（音频转换）
- Docker（可选，用于 Kaldi 引擎）

### 安装

```bash
# 克隆仓库
git clone <repo-url>
cd score_reading

# 安装依赖
pip install -e .
```

### 单文件评分

```bash
score_reading single \
    --mp3 ./samples/student1.mp3 \
    --text "Hello, my name is John. Nice to meet you." \
    --student "张三" \
    --task "reading-001" \
    --engine auto \
    --out ./data/out
```

### 查看帮助

```bash
score_reading --help
score_reading single --help
```

## 命令说明

### `single` - 单文件评分

对单个音频文件进行口语评分。

```bash
score_reading single \
    --mp3 <音频文件路径> \
    --text "<标准朗读文本>" \
    --student "<学生ID或姓名>" \
    --task "<任务ID>" \
    --engine <auto|fast|standard|pro> \
    --out <输出目录>
```

**参数说明**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mp3` | 输入音频文件（支持 MP3/WAV） | 必填 |
| `--text` | 标准朗读文本 | 必填 |
| `--student` | 学生标识 | unknown |
| `--task` | 任务标识 | default |
| `--engine` | 引擎模式 | auto |
| `--out` | 输出目录 | ./data/out |
| `--config` | 配置文件路径 | config/default.yaml |

### `run` - 批量评分（Phase 2）

根据 manifest CSV 批量处理多个音频。

```bash
score_reading run \
    --manifest submissions.csv \
    --tasks tasks.yaml \
    --engine auto \
    --jobs 4 \
    --out ./data/out
```

### `validate` - 校验输入（Phase 2）

检查 manifest 中的文件是否存在。

```bash
score_reading validate \
    --manifest submissions.csv \
    --tasks tasks.yaml
```

### `report` - 重新生成 HTML

从 JSON 结果重新生成 HTML 报告。

```bash
score_reading report \
    --json ./data/out/task/student/sub_xxx.json \
    --output ./report.html
```

## 输出格式

### JSON 结构

```json
{
  "meta": {
    "task_id": "reading-001",
    "student_id": "张三",
    "submission_id": "sub_20260201183000_abc123",
    "engine_used": "standard",
    "fallback_chain": []
  },
  "scores": {
    "overall_100": 85.0,
    "pronunciation_100": 82.0,
    "fluency_100": 88.0,
    "intonation_100": 80.0,
    "completeness_100": 90.0
  },
  "alignment": {
    "words": [
      {"word": "hello", "start": 0.5, "end": 0.9, "tag": "ok", "score": 85.0}
    ]
  },
  "feedback": {
    "cn_summary": "整体表现良好，注意 TH 音的发音",
    "cn_actions": ["练习舌尖放在上下齿之间..."]
  }
}
```

### HTML 报告

生成的 HTML 报告包含：

- 📊 综合评分和四维子分
- 📝 逐词高亮的朗读文本（绿色=正确，黄色=待加强，红色=缺失）
- 🔍 需要加强的词和音素分析
- 💡 针对性的发音改进建议

## 引擎说明

| 引擎 | 说明 | 适用场景 |
|------|------|----------|
| `auto` | 根据音频质量自动选择 | 默认推荐 |
| `fast` | 基于 Gentle 的容错对齐 | 音频质量差、快速处理 |
| `standard` | 基于 Kaldi-GOP 的精确评分 | 正常音频 |
| `pro` | 高级模型（预留） | 未来扩展 |

### Auto 选择策略

- 音频时长 < 2.5s → fast
- 静音占比 > 35% → fast
- RMS < -28dB → fast
- 其他 → standard

### 失败回退

- standard 失败 → fast
- standard 成功但漏词 > 25% → fast
- pro 失败 → standard → fast

## Docker 部署

### 构建镜像

```bash
cd docker
docker-compose build
```

### 运行服务

```bash
# 启动所有服务
docker-compose up -d

# 仅启动 Gentle（Fast 引擎）
docker-compose up -d gentle
```

### 使用 Docker 评分

```bash
# 将音频放入 data/in 目录
docker-compose run app single \
    --mp3 /app/data/in/student1.mp3 \
    --text "Hello world" \
    --student student1 \
    --task test
```

## 目录结构

```
score_reading/
├── src/
│   ├── cli.py                # CLI 入口
│   ├── models.py             # 数据模型
│   ├── config.py             # 配置管理
│   ├── pipeline/             # 处理流水线
│   │   ├── preprocess.py     # 预处理
│   │   ├── router.py         # 引擎路由
│   │   ├── normalize.py      # 分数归一化
│   │   ├── analyze.py        # 结果分析
│   │   └── engines/          # 评分引擎
│   ├── report/               # 报告生成
│   └── advice/               # 建议生成
├── config/
│   └── default.yaml          # 默认配置
├── advice/
│   └── phoneme_rules.yaml    # 音素规则库
├── docker/                   # Docker 配置
├── data/
│   ├── in/                   # 输入目录
│   ├── out/                  # 输出目录
│   └── models/               # 模型目录
└── tests/                    # 测试用例
```

## 配置说明

主要配置项位于 `config/default.yaml`：

```yaml
# 音频质量阈值
quality_thresholds:
  min_duration_sec: 2.5
  max_silence_ratio: 0.35
  min_rms_db: -28

# 分析配置
analysis:
  weak_words_top_n: 3
  weak_phonemes_top_n: 2

# 报告颜色
report:
  colors:
    ok: "#4CAF50"
    weak: "#FFC107"
    missing: "#F44336"
```

## 开发

### 安装开发依赖

```bash
pip install -e ".[dev]"
```

### 运行测试

```bash
pytest tests/
```

### 代码格式化

```bash
ruff check --fix .
ruff format .
```

## License

MIT
