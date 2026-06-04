# Fund Research Platform

**AI-oriented 开源个人基金研究平台**

面向个人研究者、量化学习者和 AI Agent 的可信基金研究底座。在免费公开数据约束下，提供可解释、可追踪、可复现的基金研究能力。

> ✅ **第零阶段完成（2026-06-04）— 30 只样本基金 100% 拉取成功，一期数据基础已验证**
>
> 详细需求文档：[需求书 v0.4](./AI-oriented开源个人基金研究平台需求书_v0.4.md) | 第零阶段总结：[conclusion.md](./docs/phase0/conclusion.md)

## 核心理念

- **不追求机构级数据完整性**，追求在免费数据约束下把研究方法、算法口径和证据系统做扎实
- **先建设可信底座，再增强算法**：不是先做功能齐全的平台，而是先验证数据能撑住什么，再逐步加算法
- **估计隔离**：模拟持仓、动态归因等估计结果必须使用 `estimated_*` 字段，不进入默认评分和高置信度结论

## 快速开始

### 环境要求

- Python >= 3.11, < 3.13（推荐 3.12）
- Git

### 安装

```bash
# 克隆仓库
git clone <repo-url>
cd fund-research

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -e ".[dev]"

# 复制环境配置
cp .env.example .env

# 初始化数据库
fund-research init

# 启动 API 服务
fund-research serve

# 访问 API 文档
# http://127.0.0.1:8000/docs
```

### CLI 命令

```bash
fund-research --help          # 查看帮助
fund-research version         # 版本信息
fund-research init            # 初始化数据库
fund-research init -d ./mydb.duckdb  # 指定数据库路径
fund-research serve           # 启动 API (默认 :8000)
fund-research serve -p 9000   # 指定端口
fund-research check-data      # 数据源健康检查（第零阶段实现）
fund-research update          # 更新本地数据（第零阶段实现）
```

## 项目结构

```
fund-research/
├── config/                          # 非 Python 配置文件
│   ├── alembic.ini                  # 数据库迁移配置
│   └── metrics_registry_template.yaml  # 指标注册表模板
├── src/fund_research/               # Python 包
│   ├── core/                        # 核心领域模型
│   │   ├── enums.py                 # 枚举定义（基金类型、数据源等级、结论状态等）
│   │   └── schemas.py               # Pydantic 模型（APIResponse, ResearchPacket, Evidence）
│   ├── db/                          # 数据库层
│   │   ├── models.py                # SQLAlchemy ORM 模型（20 张一期核心表）
│   │   ├── session.py               # 会话管理（DuckDB/SQLite）
│   │   └── migrations/              # Alembic 迁移脚本
│   ├── config/                      # Python 配置
│   │   └── settings.py              # pydantic-settings 全局配置
│   ├── data/                        # 数据层
│   │   ├── adapters/                # 数据源适配器（基类接口）
│   │   └── quality.py               # 数据质量检查
│   ├── analysis/                    # 分析算法（见分期计划）
│   ├── research/                    # 研究包、证据链（见分期计划）
│   ├── api/                         # FastAPI Tool API
│   │   ├── app.py                   # 应用入口
│   │   ├── router.py                # 路由定义（一期 5 个接口）
│   │   └── deps.py                  # 依赖注入
│   ├── cli/                         # CLI 入口
│   │   └── main.py                  # typer CLI
│   └── utils/                       # 工具函数
│       └── logging.py               # loguru 日志配置
├── tests/                           # 测试
├── notebooks/examples/              # Notebook 示例
├── docs/                            # 文档
├── data/                            # 本地数据（gitignored）
├── pyproject.toml                   # 项目元数据和依赖
├── .env.example                     # 环境变量模板
└── .gitignore
```

## 一期 Tool API（5 个接口）

| 接口 | 说明 |
|------|------|
| `GET /api/v1/funds/{code}/profile` | 基金基本信息、经理、分类、规模、费率 |
| `GET /api/v1/funds/{code}/nav-metrics` | 净值指标：收益、回撤、夏普、卡玛等 |
| `GET /api/v1/funds/{code}/holdings` | 公开披露持仓（按报告期） |
| `POST /api/v1/analysis/exposure` | 风格/行业暴露 + 静态归因 |
| `POST /api/v1/research/packet` | 生成研究包（JSON + Markdown） |

每个接口返回统一结构：`{data, metadata, evidence, warnings, conclusion_status}`

## 分期计划

| 阶段 | 目标 | 状态 |
|------|------|------|
| 框架搭建 | 项目结构、依赖、数据模型、API 骨架 | ✅ 完成 |
| 第零阶段 | 数据可得性与口径试验 | ✅ 完成 |
| 一期 | 可信 AI-ready MVP（单基金体检 + 研究包 + 证据链） | 🔜 进行中 |
| 二期 | 算法验证与受控估计（模拟持仓实验、综合评分基础版） | 📋 计划中 |
| 三期 | 发现能力与研究工作台（基金画像指纹、相似基金、异常发现） | 📋 计划中 |
| 四期 | ETF/指数、组合与更多资产类型 | 📋 计划中 |
| 五期 | Agent 化研究与开源生态 | 📋 计划中 |

详见需求文档第 12 章。

## 开发

```bash
# 运行测试
pytest

# 代码检查
ruff check src/ tests/

# 类型检查
mypy src/

# 生成数据库迁移
alembic revision --autogenerate -m "description"

# 执行数据库迁移
alembic upgrade head
```

## 免责声明

本平台所有算法结果仅用于个人研究和方法验证，不构成投资建议。
