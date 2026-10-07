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

锅不可标「已出胶」，除非最近一次煮胶峰值 **≥ 90℃**。规则在 `backend/app/domain.py`。

### 冷却架位

已出胶的锅要**拨回冷锅**，必须先占用一个**未释放**的冷却架位（架位号 1–20 的正整数）：

- 架位不参与「已出胶」判定；登记峰值、标已出胶都不看架位。
- 同一架位号至多一条未释放占用——别锅撞车禁止入库；同一锅未释放占用也至多一条。
- 操作工（worker）与管理员均可**占位**；**释放只给管理员**。
- 顶栏可进入「锅位作业台」与「冷却架」专页；冷却架支持按锅筛选、占位、释放。
- 并发抢同一架位号时，由数据库的两个 Postgres 部分唯一索引（`uq_rack_slot_open`、`uq_rack_kettle_open`）兜底，只许一条占用入库，败者收到中文 409。
- 种子数据：恰好一锅「已出胶」（锅-3），冷却架零占用。


## 快速启动

```bash
cd GlueKettle/GlueKettle-01
docker compose up --build
```
