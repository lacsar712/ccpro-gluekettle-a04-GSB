# GlueKettle-01 · 骨巷熬胶坊

一排熬锅作业台。登录后是横向锅位，点锅登记煮胶峰值并改状态。前端是原生 JS，没有 React/Vue/Svelte。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web API | Starlette 路由表（不是 FastAPI Depends） |
| 结构 | SQLModel 实体 + `domain.py` 门槛 |
| 数据 | SQLModel / SQLAlchemy · psycopg2 · PostgreSQL 15 |
| 前端 | 原生 ES Module · Vite 仅打包 |
| 部署 | Docker Compose |

## 路径与端口

- 前端：http://localhost:4790
- API：http://localhost:8790
- PostgreSQL：localhost:6190

## 演示账号

`admin` / `123456`，`worker` / `123456`

## 业务规则

- 锅不可标「已出胶」，除非最近一次煮胶峰值 **≥ 90℃**。规则在 `backend/app/domain.py`。
- **已出胶拨回冷锅**：该锅必须先持有一条**未释放的冷却架占位**；架位不参与已出胶判定，登记峰值、标已出胶都不看架位。
- **冷却架位**：架位号为正整数 **1–20**；同一锅未释放占用最多一条；同一架位号全坊只许一条未释放占用（跨锅撞号也禁止）。由部分唯一索引 `uq_rack_open_slot` / `uq_rack_open_kettle` 在库内兜底，并发抢同一号只许一条入库。
- **权限**：登录操作工（worker）即可占位；释放架位仅管理员（admin）。顶栏可在「锅位作业台」与「冷却架」之间切换，冷却架页支持按锅筛选、占位、释放。

## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
