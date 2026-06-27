# IOE — 鞋店进销存管理系统 v1

一站式鞋类零售进销存解决方案:商品管理、扫码出入库、销售收银、会员管理、资金流水、AI 拍照识别进货单。

[![Django](https://img.shields.io/badge/Django-4.2-green.svg)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-brightgreen.svg)](https://www.docker.com/)
[![MinIO](https://img.shields.io/badge/MinIO-S3%20Compatible-orange.svg)](https://min.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 目录

- [项目概述](#项目概述)
- [技术栈](#技术栈)
- [功能模块](#功能模块)
- [系统架构](#系统架构)
- [数据库表结构](#数据库表结构)
- [快速开始 (Docker Compose)](#快速开始-docker-compose)
- [环境变量](#环境变量)
- [外部集成](#外部集成)
- [项目结构](#项目结构)
- [开发指南](#开发指南)
- [部署说明](#部署说明)
- [常见问题](#常见问题)

---

## 项目概述

IOE 是一个基于 **Django 4.2** 的鞋类零售进销存管理系统，专为鞋店设计。核心场景:

- **进货**:扫码入库、批量录入、AI 拍照识别进货单(支持任意供应商格式)
- **销售**:收银台(POS)、会员折扣、多支付方式
- **库存**:实时库存、扫码出入库、库存预警、盘点
- **会员**:等级折扣、积分、余额充值、消费记录
- **资金**:钱进钱出一本账(销售收入 + 充值 - 进货成本)
- **报表**:销售趋势、商品排行、利润分析、会员分析
- **对外 API**:为内容平台(小红书)提供只读鞋款数据接口

### 适用场景

- 鞋店 / 服装店日常进销存管理
- 小型零售仓库库存跟踪
- 多供应商、多款号(SPU) + 多色码(SKU) 管理模式

---

## 技术栈

| 层级 | 技术 | 说明 |
|---|---|---|
| **后端框架** | Django 4.2 | Python 3.10 |
| **数据库** | PostgreSQL 15 | 开发/生产均用 PG,SQLite 仅兜底 |
| **对象存储** | MinIO (S3 兼容) | 商品图片存储,通过 django-storages + boto3 |
| **Web 服务器** | Gunicorn | `--timeout 180`(适配 AI 识别长请求) |
| **容器化** | Docker Compose | 开发一键启动(db + minio + web) |
| **前端** | Bootstrap 5 + Bootstrap Icons | crispy-bootstrap5 表单渲染 |
| **条码** | JsBarcode (浏览器端) | EAN-13 贴纸生成 + 打印 |
| **AI 识别** | Dify 工作流 | 截图识别进货单(视觉模型) |
| **弹窗/提示** | SweetAlert2 | 删除确认等交互 |

### Python 依赖

```
Django>=4.2.0          psycopg2-binary>=2.9.9   gunicorn>=21.2.0
django-storages>=1.14  boto3>=1.34              Pillow>=10.1.0
django-crispy-forms>=2.1  crispy-bootstrap5>=0.7  django-bootstrap5>=23.3
django-widget-tweaks>=1.4.12  requests>=2.31.0  openpyxl>=3.1.2
qrcode>=8.1            psutil>=7.0.0            Faker>=37.1.0
```

---

## 功能模块

### 商品管理

- **SPU/SKU 模型**:款号(`model_no`) 聚合同款不同颜色/尺码,`barcode` 为业务条码,`scan_code` 为 EAN-13 贴纸码
- **8 个鞋类目**:运动鞋、休闲鞋、凉鞋/拖鞋、靴子、高跟鞋、平底鞋、帆布鞋、皮鞋(一级类目,编码驱动)
- **商品图片**:按款共享,支持多图(白底主图/模特图/细节图/侧面/鞋底/上脚),存 MinIO
- **批量操作**:CSV 导入导出、批量修改供应商
- **条码贴纸打印**:选中色码 → JsBarcode 浏览器渲染 EAN-13 SVG → `window.print()` 打印

### 库存管理

- **实时库存**:`Inventory` 表一对一商品,`select_for_update()` 行锁防并发
- **入库/出库/调整**:每次操作写 `InventoryTransaction` 流水(不可改)
- **扫码出入库**:支持扫码枪,自动匹配 `barcode` 或 `scan_code`,连续扫
- **批量进货**:手填 formset 批量录入(每行一款)
- **库存预警**:`warning_level` 阈值,低于阈值红色标记
- **库存流水**:按款号/类型/日期筛选,查看所有进出记录

### AI 拍照识别进货单

- **流程**:上传任意供应商进货单截图 → Dify 工作流(视觉模型)识别 → 返回 JSON 预填表单 → 用户补类目+成本 → 确认入库
- **通用性**:不依赖固定模板,AI 读图提取 `[{model_no, name, size, color, quantity, price}]`
- **支持方向**:进货(IN) / 退货(OUT) 自动判断
- **配置**:Dify 工作流 API Key + Base URL 填 `.env` 即可启用

### 销售管理 (POS 收银台)

- **销售单**:选择商品 + 会员(可选) → 折扣 → 支付(现金/微信/支付宝/银行卡/余额/混合)
- **会员权益**:自动积分、余额支付、等级折扣
- **退货**:销售单取消 → 库存自动回退
- **记录查询**:按日期/会员/状态筛选

### 会员管理

- **会员信息**:姓名、手机号(唯一)、等级、生日
- **等级体系**:自定义等级 + 折扣率
- **余额充值**:充值记录独立存储,支持多种支付方式
- **积分**:消费自动累积
- **导入导出**:CSV 批量导入/导出会员

### 资金流水 (账本)

- **三流合一**:销售收入 + 会员充值 = 收入;进货(入库 × 成本价) = 支出
- **汇总卡片**:本期收入 / 支出 / 净额
- **筛选**:日期段 + 类型(销售/充值/进货)
- **分页**:每页 30 笔,最新在上

### 报表中心

- 销售趋势、商品排行(Top N)、库存周转、利润分析
- 会员分析(消费排行、RFM)、会员生日提醒
- 充值报表、操作日志审计

### 库存盘点

- 盘点计划 → 执行(录实际数) → 审核 → 自动调整库存
- 差异报告

### 系统管理

- **用户管理**:创建/编辑/删除系统用户
- **操作日志**:141+ 条,记录所有关键操作(谁、什么时候、做了什么)
- **备份管理**:数据库备份/恢复/下载
- **系统维护**:缓存清理、健康检查

### 对外 API (小红书内容工厂)

- `GET /api/external/shoe-models/` — 按款号聚合的鞋款列表(分页,含主图、类目、SKU 数、价格区间)
- `GET /api/external/shoe-models/<model_no>/` — 单款详情(所有色码 + 全部图片)
- 认证:`X-Api-Key` 请求头,`hmac.compare_digest` 防时序攻击
- 只读、无 CSRF、无 CORS(服务器间调用)

---

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    浏览器 (Bootstrap 5)                │
│  商品管理 │ 库存管理 │ 销售收银 │ 会员 │ 资金流水 │ 报表  │
└────────────────────────┬─────────────────────────────┘
                         │ HTTP
┌────────────────────────▼─────────────────────────────┐
│              Gunicorn (Django 4.2 WSGI)               │
│                  --timeout 180                         │
│                                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ product  │ │inventory │ │  sales   │ │  member  │ │
│  │  views   │ │  views   │ │  views   │ │  views   │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │            │            │            │         │
│  ┌────┴────────────┴────────────┴────────────┴─────┐  │
│  │              models + services                   │  │
│  │  Product / Inventory / Sale / Member / ...       │  │
│  └──────────────────────┬──────────────────────────┘  │
└─────────────────────────┼─────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
┌───────▼───────┐ ┌───────▼───────┐ ┌───────▼───────┐
│  PostgreSQL 15 │ │ MinIO (S3)    │ │  Dify (可选)   │
│  业务数据      │ │ 商品图片      │ │ AI 识别进货单  │
└───────────────┘ └───────────────┘ └───────────────┘
```

### 数据流

1. **进货**:扫码/批量录入/AI 识别 → `update_inventory(product, qty, 'IN')` → Inventory +1, InventoryTransaction +1
2. **销售**:创建 Sale → SaleItem → `update_inventory(product, -qty, 'OUT')` → Inventory -1
3. **资金流水**:聚合 Sale(COMPLETED) + RechargeRecord + InventoryTransaction(IN×cost) → 统一账本

---

## 数据库表结构

共 **21 张表**,核心表如下:

### 商品模块

| 表名 | 说明 | 关键字段 | 当前行数 |
|---|---|---|---|
| `inventory_product` | 商品 SKU | barcode, scan_code, model_no, name, color, size, cost, price, category, supplier | 16 |
| `inventory_category` | 鞋类目(8 个一级) | name, code, l1_code | 8 |
| `inventory_productimage` | 商品图片(存 MinIO 路径) | product, image, image_type, is_primary | 6 |
| `inventory_supplier` | 供应商 | name, contact | 2 |

### 库存模块

| 表名 | 说明 | 关键字段 | 当前行数 |
|---|---|---|---|
| `inventory_inventory` | 实时库存(1:1 Product) | product, quantity, warning_level | 16 |
| `inventory_inventorytransaction` | 库存流水(不可改) | product, transaction_type(IN/OUT/ADJUST), quantity, supplier, operator, transaction_date | 54 |

### 销售模块

| 表名 | 说明 | 关键字段 | 当前行数 |
|---|---|---|---|
| `inventory_sale` | 销售单 | member, total_amount, discount_amount, final_amount, payment_method, status(COMPLETED/CANCELLED), operator | 2 |
| `inventory_saleitem` | 销售明细 | sale, product, quantity, price | 2 |

### 会员模块

| 表名 | 说明 | 关键字段 | 当前行数 |
|---|---|---|---|
| `inventory_member` | 会员 | name, phone(唯一), level, balance, points | 0 |
| `inventory_memberlevel` | 会员等级 | name, discount_rate | 0 |
| `inventory_rechargerecord` | 充值记录 | member, amount, actual_amount, payment_method | 0 |

### 系统模块

| 表名 | 说明 | 关键字段 | 当前行数 |
|---|---|---|---|
| `inventory_operationlog` | 操作日志 | operator, action, content_type, object_id, detail(JSON) | 141 |

> 完整表结构及字段说明见 [数据库表结构详解](#数据库表结构) 章节,或直接查看 `inventory/models/` 目录下的模型定义。

---

## 快速开始 (Docker Compose)

### 前置要求

- Docker + Docker Compose
- Git

### 1. 克隆项目

```bash
git clone https://github.com/zhtyyx/ioe.git
cd ioe
```

### 2. 配置环境变量

```bash
cp .env.template .env
```

编辑 `.env`,至少修改:

```ini
SECRET_KEY=你的随机密钥
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DB_PASSWORD=你的数据库密码
MINIO_ROOT_PASSWORD=你的MinIO密码
```

### 3. 启动服务

```bash
docker compose up -d
```

启动后:

| 服务 | 地址 | 说明 |
|---|---|---|
| IOE 系统 | `http://localhost:8000` | 主系统 |
| MinIO API | `http://localhost:9002` | S3 兼容存储 |
| MinIO Console | `http://localhost:9003` | MinIO Web 管理界面 |

### 4. 创建管理员

```bash
docker compose exec web python manage.py createsuperuser
```

### 5. 初始化数据(可选)

```bash
# 初始化 8 个鞋类目
docker compose exec web python manage.py seed_shoe_categories

# 生成示例商品 + 库存数据
docker compose exec web python manage.py generate_sample_data
```

### 6. 访问系统

浏览器打开 `http://localhost:8000`,用刚才创建的管理员账号登录。

---

## 环境变量

完整配置见 `.env.template`:

### Django 核心

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEBUG` | `True` | 开发 True,生产 False |
| `SECRET_KEY` | (内置默认) | Django 密钥,**生产必须改** |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | 逗号分隔,生产加域名 |
| `LANGUAGE_CODE` | `zh-hans` | 中文 |
| `TIME_ZONE` | `Asia/Shanghai` | 上海时区 |

### 数据库 (PostgreSQL)

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DB_ENGINE` | `django.db.backends.sqlite3` | Docker 环境自动覆盖为 postgresql |
| `DB_NAME` | `inventory_db` | 数据库名 |
| `DB_USER` | `db_user` | 数据库用户 |
| `DB_PASSWORD` | `db_password` | 数据库密码 |
| `DB_HOST` | `db` | 容器内服务名 |
| `DB_PORT` | `5432` | 端口 |

### MinIO (对象存储)

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MINIO_ROOT_USER` | `minioadmin` | Access Key |
| `MINIO_ROOT_PASSWORD` | `minioadmin` | Secret Key |
| `MINIO_BUCKET` | `ioe-media` | 存储桶名 |
| `MINIO_ENDPOINT` | `http://minio:9000` | S3 API 端点(容器内) |
| `MINIO_PUBLIC_DOMAIN` | `localhost:9002/ioe-media` | 对外访问域名 |

### Dify (AI 识别进货单,可选)

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DIFY_BASE_URL` | (空) | Dify API 地址,如 `http://host.docker.internal:5001` |
| `DIFY_RECEIPT_API_KEY` | (空) | Dify 工作流 API Key(`app-xxxx`) |

### 小红书 API (可选)

| 变量 | 默认值 | 说明 |
|---|---|---|
| `XHS_API_KEY` | (空) | 对外只读 API 密钥,为空则 API 返回 503 |

---

## 外部集成

### 1. Dify — AI 拍照识别进货单

**功能**:上传任意供应商进货单截图,AI 自动识别商品明细,预填表单,用户确认后入库。

**配置步骤**:

1. 在 Dify 控制台创建「工作流」应用,添加视觉模型节点
2. System Prompt:
   > 你是鞋类进货单识别助手。识别这张进货单截图,提取每个商品明细。严格返回 JSON 数组,每项:`{"model_no":货号, "name":商品名, "size":尺码, "color":颜色, "quantity":数量(整数), "price":单价(数字)}`。只返回 JSON 数组本体,不要 markdown 代码块。
3. 发布 → 获取 API Key(`app-xxxx`)
4. 填入 `.env`:`DIFY_BASE_URL` + `DIFY_RECEIPT_API_KEY`
5. 重启 web:`docker compose restart web`

**使用**:库存管理页 → 「拍照识别单据」→ 上传截图 → 等待 AI 识别 → 补类目+成本 → 确认入库

### 2. 小红书内容工厂 — 只读鞋款 API

**功能**:为外部内容平台提供鞋款数据(款号、图片、价格、库存),用于内容创作。

**端点**:

```bash
# 鞋款列表(分页)
curl -H "X-Api-Key: your-key" http://localhost:8000/api/external/shoe-models/?page=1&page_size=20

# 单款详情
curl -H "X-Api-Key: your-key" http://localhost:8000/api/external/shoe-models/882/
```

**配置**:`.env` 中设置 `XHS_API_KEY`,外部调用时通过 `X-Api-Key` 请求头传递。

---

## 项目结构

```
ioe/
├── Dockerfile                    # 容器镜像
├── docker-compose.yml            # 开发环境(db + minio + web)
├── docker-compose.prod.yml       # 生产环境(db + web,MinIO 外部)
├── requirements.txt              # Python 依赖
├── manage.py                     # Django 管理入口
├── .env.template                 # 环境变量模板
│
├── inventory/                    # 主 Django App
│   ├── settings.py               # Django 配置(含 MinIO/Dify/XHS)
│   ├── urls.py                   # 路由(80+ 条)
│   ├── wsgi.py / asgi.py         # WSGI/ASGI 入口
│   │
│   ├── models/                   # 数据模型(6 个模块)
│   │   ├── product.py            # Product, Category, Supplier, ProductImage
│   │   ├── inventory.py          # Inventory, InventoryTransaction, StockAlert
│   │   ├── inventory_check.py    # InventoryCheck, InventoryCheckItem
│   │   ├── sales.py              # Sale, SaleItem
│   │   ├── member.py             # Member, MemberLevel, RechargeRecord
│   │   └── common.py             # OperationLog, SystemConfig
│   │
│   ├── views/                    # 视图(按模块拆分)
│   │   ├── core.py               # 首页、报表入口
│   │   ├── product.py            # 商品 CRUD、导入导出、条码打印
│   │   ├── inventory.py          # 库存管理、扫码出入库、资金流水、AI 识别
│   │   ├── sales.py              # 销售单、收银台
│   │   ├── member.py             # 会员管理
│   │   ├── barcode.py            # 条码查询 API
│   │   ├── supplier.py           # 供应商管理
│   │   ├── api_external.py       # 对外只读 API(小红书)
│   │   └── system.py             # 系统管理(日志/备份/用户)
│   │
│   ├── forms/                    # 表单(7 个模块)
│   │   ├── product_forms.py      # ProductForm, CategoryForm, ProductImageFormSet
│   │   ├── inventory_forms.py    # InventoryTransactionForm, BatchPurchaseFormSet
│   │   ├── sales_forms.py        # SaleForm, SaleItemForm
│   │   ├── member_forms.py       # MemberForm, RechargeForm
│   │   └── ...
│   │
│   ├── services/                 # 业务逻辑层
│   │   ├── inventory_service.py  # 库存更新(select_for_update)
│   │   ├── product_service.py    # 商品查询/聚合
│   │   ├── member_service.py     # 会员积分/余额
│   │   ├── report_service.py     # 报表数据聚合
│   │   ├── backup_service.py     # 备份/恢复
│   │   └── export_service.py     # Excel 导出
│   │
│   ├── templates/inventory/      # Django 模板
│   │   ├── base.html             # 基础布局+导航
│   │   ├── index.html            # 首页仪表盘
│   │   ├── product_list.html     # 商品列表(SPU/SKU 展开)
│   │   ├── inventory_list.html   # 库存管理
│   │   ├── sale_form.html        # 收银台
│   │   ├── cash_flow.html        # 资金流水
│   │   ├── scan_in.html          # 扫码入库
│   │   ├── scan_out.html         # 扫码出库
│   │   └── ...
│   │
│   ├── management/commands/      # 管理命令
│   │   ├── generate_sample_data.py
│   │   ├── seed_shoe_categories.py
│   │   └── seed_suppliers.py
│   │
│   ├── utils/                    # 工具函数
│   ├── templatetags/             # 自定义模板标签
│   ├── tests/                    # 测试
│   └── migrations/               # 数据库迁移(19 个)
│
├── logs/                         # 应用日志
├── media/                        # 本地媒体(MinIO 配置后为空)
├── staticfiles/                  # 收集的静态文件
├── db/                           # SQLite 兜底数据库
└── asset/                        # 文档截图
```

---

## 开发指南

### 本地开发(不用 Docker)

```bash
# 1. 创建虚拟环境
python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 .env(数据库用 SQLite 即可)
DEBUG=True
DB_ENGINE=django.db.backends.sqlite3

# 4. 迁移 + 初始化
python manage.py migrate
python manage.py seed_shoe_categories
python manage.py createsuperuser

# 5. 启动开发服务器
python manage.py runserver
```

### 修改模板/视图后注意事项

项目使用 **Gunicorn** 部署(包括开发环境),Gunicorn worker 进程会在内存中缓存编译后的 Django 模板。修改 `.html` 模板或 Python 视图代码后,**必须重启 web 容器**才能生效:

```bash
docker compose restart web
```

> 这不是浏览器缓存问题,是 gunicorn 进程级模板缓存。`manage.py runserver` 开发服务器有自动重载,但 gunicorn 没有。

### 数据库迁移

```bash
# 生成迁移文件(修改 models 后)
docker compose exec web python manage.py makemigrations

# 应用迁移
docker compose exec web python manage.py migrate
```

### 运行测试

```bash
docker compose exec web python manage.py test inventory.tests
```

---

## 部署说明

### 生产环境

1. 使用 `docker-compose.prod.yml`(不含 MinIO,需外部 S3 兼容存储)
2. 修改 `.env`:
   ```ini
   DEBUG=False
   SECRET_KEY=强随机密钥
   ALLOWED_HOSTS=你的域名
   DB_PASSWORD=强数据库密码
   MINIO_ENDPOINT=https://你的S3端点
   MINIO_PUBLIC_DOMAIN=https://你的CDN域名
   ```
3. 启动:`docker compose -f docker-compose.prod.yml up -d`
4. 前端建议加 Nginx 反向代理 + HTTPS

### 备份

- **数据库**:系统管理 → 备份管理 → 创建备份,或 `docker compose exec web python manage.py dumpdata`
- **图片(MinIO)**:备份 `minio_data` 卷,或使用 `mc mirror` 同步到远程
- **自动化**:`.env` 中 `BACKUP_ENABLED=True` + `BACKUP_INTERVAL_DAYS=7`

---

## 常见问题

### Q: 改了模板/视图,界面没变化?

A: 重启 web 容器 — `docker compose restart web`。Gunicorn 缓存编译后的模板,改磁盘文件不会自动重载。

### Q: 扫码出库扫了条码找不到商品?

A: 系统同时匹配 `barcode`(业务条码)和 `scan_code`(EAN-13 贴纸码)。检查商品编辑页两个字段是否都有值。

### Q: 出库后库存数量没变?

A: 同上,重启 web 容器。如果还不行,检查浏览器是否缓存了旧页面(Ctrl+F5 强制刷新)。

### Q: 资金流水页进货支出为什么是"估算"?

A: 库存流水表(`InventoryTransaction`)没有记录进货单价,支出按 `商品成本价 × 数量` 估算。如需精确到每批实际拿货价,后续可扩展流水表加 `unit_price` 字段。

### Q: MinIO 图片访问不到?

A: 检查:
1. MinIO 容器是否运行:`docker compose ps minio`
2. 桶是否存在:打开 `http://localhost:9003` → Buckets → `ioe-media`
3. 图片 URL 域名是否正确:`.env` 中 `MINIO_PUBLIC_DOMAIN` 需与访问端一致

### Q: Dify 识别不工作?

A: 检查:
1. `.env` 中 `DIFY_BASE_URL` 和 `DIFY_RECEIPT_API_KEY` 是否填写
2. ioe 容器能否访问 Dify:`docker compose exec web curl $DIFY_BASE_URL`
3. Dify 工作流是否已发布,视觉模型供应商是否配置

---