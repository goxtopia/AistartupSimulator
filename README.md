# AI Startup Simulator

基于 Python（FastAPI）+ HTML/CSS/JS 的 AI 创业经营模拟 WebGame。

从选择国家与创始人背景开始，组建研究团队、推进模型/素材/算力研究、采购计算池、训练并发布模型、运营 API 市场，并应对随机事件与竞争对手。

## 特性

- **配置驱动**：国家、研究树、芯片、员工特质、市场分段、事件等均在 `data/configs/*.json`
- **接口化引擎**：`IGameSystem` + `EffectApplier` + `ConfigRegistry`，系统内聚、可插拔
- **核心系统**：HR / Research / Compute / Training / Market / Events / **Competitors AI**
- **AI 对手**：9 家策略各异的实验室（闭源前沿、开源权重、安全优先、人才掠食者…），会自主研究、发模型，并从玩家处挖角
- **Logo 设计器**：SVG 形状 + 图标 + 布局 + 配色叠加
- **存档/读档**：JSON 存档于 `saves/`
- **美术**：纯 SVG / 程序生成，无外部图片依赖

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py --host 0.0.0.0 --port 8000
```

浏览器打开：http://127.0.0.1:8000

## 架构

```
AistartupSimulator/
├── backend/app/
│   ├── api/routes.py          # HTTP API
│   ├── core/config_loader.py  # 配置注册表
│   ├── engine/
│   │   ├── game.py            # 引擎编排 / 会话 / 存档
│   │   ├── effects.py         # 配置式效果应用（可注册 handler）
│   │   ├── interfaces/        # IGameSystem / IGameContext
│   │   ├── calculators/       # 纯函数：隐藏分、EVAL、市场
│   │   └── systems/           # HR / Research / Compute / Training / Market / Events
│   ├── models/schemas.py
│   └── main.py
├── data/configs/              # 全部游戏内容 JSON
├── frontend/                  # 静态前端（无构建步骤）
├── saves/
├── run.py
└── requirements.txt
```

### 扩展方式

| 想加什么 | 怎么做 |
|---------|--------|
| 新国家 / 研究 / 芯片 / 事件 | 编辑 `data/configs/*.json` |
| 新效果键（如 `unlock_x`） | `DefaultEffectApplier.register("unlock_x", handler)` |
| 新子系统 | 实现 `on_new_game` / `on_tick` / `serialize_public`，在 `GameEngine._register_systems` 注册 |
| 新创始人背景 | `founder_backgrounds.json` 增加条目 |
| 新隐藏标签 | `employees.json` → `hidden_tags` |
| 新 AI 对手 / 策略 | `competitors.json` → `rivals` / `strategies` |

### 关键公式（摘要）

- **隐藏分** = 容量 base × 架构等乘数 × 参数量曲线 × 数据类型 × 数据质量
- **EVAL 分** = 隐藏分映射 + 研究偏向 + 随机噪声（影响用户选择）
- **倾向**：开放性（开源比重）、政府关系、公众声誉、透明性（可解读性 − 政府关系惩罚）、创新性（模型研究）
- **员工满意度** = 个人倾向理想值与公司实际倾向的距离；过低会离职
- **开源 API 定价**：锁定为隐藏分最接近的已有 API 模型价格的 ±100%

## API 摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/catalog` | 全部配置目录 |
| POST | `/api/game/new` | 新游戏 |
| GET | `/api/game/state` | 状态（需 `X-Game-Id`） |
| POST | `/api/game/advance` | 推进天数 |
| POST | `/api/game/save` / `load` | 存读档 |
| POST | `/api/hr/*` | 招聘/培养/挖角 |
| POST | `/api/research/*` | 研究 |
| POST | `/api/compute/purchase` | 采购算力 |
| POST | `/api/training/*` | 数据集/训练/发布/蒸馏 |
| POST | `/api/events/choose` | 事件选项 |

## 开发

```bash
# 热重载
python run.py --reload

# 简单引擎冒烟
.venv/bin/python -c "from backend.app.engine.game import get_engine; print(get_engine().catalog().keys())"
```

## 许可证

MIT（示例项目）
