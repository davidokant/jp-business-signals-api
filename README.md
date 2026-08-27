# JP Business Signals API

## For API buyers

**Japan company search and procurement signals for supplier research, B2B sales intelligence, and market-entry products.** Every returned company and signal preserves a source URL, license note, and collection time.

- Try it on [RapidAPI](https://rapidapi.com/davidokant/api/japan-business-signals-api)
- Read the live [landing page](https://jp-business-signals-api-production.up.railway.app/)
- Inspect the interactive [OpenAPI documentation](https://jp-business-signals-api-production.up.railway.app/docs)

Core endpoints for product integration:

```text
GET /v1/companies/search
GET /v1/company-details?corporate_number=1234567890123
GET /v1/company-timeline?corporate_number=1234567890123&limit=50&offset=0
GET /v1/procurement-signals?since=2026-08-20&q=software&prefecture=Tokyo
GET /v1/tenders/search?q=cloud&prefecture=Tokyo&category=services
GET /v1/company-tender-matches?corporate_number=1234567890123&q=cloud
GET /v1/signals
```

The activity score is a transparent product metric based on observed public activity. It is not a credit score and must not be used for decisions about people, employment, insurance, housing, or other high-impact contexts.

一个可运行的 API 市场 MVP：把有来源记录的日本企业公开资料整理为公司检索、企业详情、经营信号和活动时间线接口。

当前版本默认装载**合成样本**，用于验证接口、定价和客户需求，不代表真实企业。真实 gBizINFO 数据接入必须使用申请获得的访问令牌，并遵守来源条款。

## 本地启动

需要 Python 3.12 以上和 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync --extra dev
Copy-Item .env.example .env
uv run uvicorn jp_business_signals.main:app --reload
```

打开 `http://127.0.0.1:8000/` 查看自助落地页与免费采购信号搜索，打开 `http://127.0.0.1:8000/docs` 查看交互式 OpenAPI 文档。正式 `/v1` 接口需要：

```text
X-API-Key: dev-local-key
```

## 接口

```text
GET /health
GET /demo/stats
GET /demo/signals?q=Sakura&limit=6
GET /v1/companies/search
GET /v1/companies/{corporate_number}
GET /v1/companies/{corporate_number}/timeline
GET /v1/procurement-signals
GET /v1/tenders/search
GET /v1/signals
GET /v1/sources
```

`/demo/*` 无需密钥，按客户端 IP 限制为每分钟 60 次，供潜在用户先体验数据质量。页面中的套餐是上架草案；在支付平台和公开部署完成前不会收款。

示例：

```powershell
Invoke-RestMethod `
  -Headers @{"X-API-Key"="dev-local-key"} `
  -Uri "http://127.0.0.1:8000/v1/companies/search?prefecture=Tokyo&min_activity_score=60"
```

## 官方开放采购机会（KKJ）

v1/tenders/search 为日本中小企业厅官公需信息门户的官方搜索 API 提供了安全的标准化入口。它仅返回适合产品展示的公告元数据与原始来源链接；不会转发公告全文、附件或可能出现的个人联系信息。

`/v1/company-tender-matches` 将一家公司已登记的地区、公开采购活动和活动评分与指定能力关键词的官方招标结果结合，返回可解释的相关性评分与投标准备简报（截止日紧迫度、资格字段是否存在、数据完整度、下一步动作）。它不声称企业具备投标资格，也不预测中标。

该功能默认关闭。启用前必须复核来源条款、在服务和 RapidAPI 页面标注来源与链接，并确认计划中的付费再分发方式符合运营方要求。详情和可直接发送的确认邮件见 docs/kkj-tender-source-review.md。

## 数据导入

重新导入内置合成样本：

```powershell
uv run jpbs-ingest sample --reset
```

导入自己的 JSON 文件：

```powershell
uv run jpbs-ingest json .\path\to\dataset.json
```

文件格式参见 [`data/sample_dataset.json`](data/sample_dataset.json)。每条记录必须保留来源名称、来源 URL、许可和采集时间。生产环境不应导入许可不明、需要登录、明确禁止自动访问或包含不必要个人信息的资料。

## 接入 gBizINFO

gBizINFO 官方 API 允许商用，但需要申请访问令牌，并要求按照申请时申报的目的使用。运行前请阅读：

- [API 与下载功能使用条款](https://help.info.gbiz.go.jp/hc/ja/articles/4999421139102-API-%E3%83%87%E3%83%BC%E3%82%BF%E3%83%80%E3%82%A6%E3%83%B3%E3%83%AD%E3%83%BC%E3%83%89%E5%88%A9%E7%94%A8%E8%A6%8F%E7%B4%84)
- [API 商用说明](https://help.info.gbiz.go.jp/hc/ja/articles/5028869912094-REST-API%E3%81%8A%E3%82%88%E3%81%B3%E5%8F%96%E5%BE%97%E3%81%97%E3%81%9F%E3%83%87%E3%83%BC%E3%82%BF%E3%82%92%E5%95%86%E7%94%A8%E5%88%A9%E7%94%A8%E5%8F%AF%E8%83%BD%E3%81%A7%E3%81%99%E3%81%8B)
- [访问令牌申请页面](https://info.gbiz.go.jp/hojin/various_registration/form)

推荐运行安全配置脚本。输入不会显示在终端，脚本会把令牌写入已被 Git 忽略的本地 .env：

    .\scripts\configure_gbiz_token.ps1
    uv run jpbs-ingest gbiz --from 20260801 --to 20260826 --max-pages 5 --terms-confirmed

如果 PowerShell 阻止运行本地脚本，可以只为这一次调用放宽策略：

    powershell -ExecutionPolicy Bypass -File .\scripts\configure_gbiz_token.ps1

同步器使用官方 v2 公司资料与采购日期更新端点，默认每个端点最多读取五页，串行请求，并对 HTTP 429 和临时服务器错误退避重试。它不会绕过访问限制。需要临时跳过采购端点时增加 --skip-procurement。来源登记和当前排除项见 [来源登记](docs/source-register.md)。

## API 市场接入

RapidAPI 上架文案和套餐草案见 [`docs/rapidapi-listing.md`](docs/rapidapi-listing.md)。生产部署时设置 `APP_RAPIDAPI_PROXY_SECRET`，服务会接受 RapidAPI 发送的 `X-RapidAPI-Proxy-Secret`；直接客户仍可使用 `X-API-Key`。

## 测试与检查

```powershell
uv run pytest
uv run ruff check .
```

## 发布准备

上线前先执行本地预检；它会运行检查、测试和构建，但不会上传任何内容：

```powershell
.\scripts\release_preflight.ps1
```

准备好空的 GitHub 仓库后，可用下列脚本完成首个受保护提交和推送。脚本会拒绝提交 `.env` 或生产数据库：

```powershell
.\scripts\publish_to_github.ps1 `
  -RepositoryUrl "https://github.com/YOUR_ACCOUNT/jp-business-signals-api.git" `
  -AuthorName "YOUR NAME" `
  -AuthorEmail "YOUR_EMAIL"
```

Railway 的持久化数据库、密钥、数据库上传和验证步骤见 [`docs/railway-deploy.md`](docs/railway-deploy.md)。

## MVP 边界

- SQLite 适合验证产品，不承担大规模并发。获得首批付费客户后再迁移 PostgreSQL。
- 当前限流器保存在单进程内存。多实例部署应换成 Redis 或 API 网关限流。
- 项目没有绕过验证码、登录、付费墙或来源访问限制的代码。
- 对外评分只是可解释的活动指标，不用于个人信用、就业、保险等高风险决策。
- 当前评分公式见 [评分说明](docs/scoring.md)，获得真实客户反馈前不应宣传为预测模型。
