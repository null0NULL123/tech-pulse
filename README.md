# Signal

每周自动从顶级工程博客收集文章，用 AI 生成中文技术周报，发送到你的邮箱。

## 背景

作为程序员，保持对前沿技术的敏感度是刚需。但现实中存在几个问题：

- **信息源分散**：GitHub Blog、Meta Engineering、Netflix Tech Blog、The Pragmatic Engineer、Simon Willison... 每个都值得追，但逐个访问太耗时
- **语言门槛**：最优质的工程博客几乎全是英文，快速消化需要额外精力
- **时间成本**：每周花 2-3 小时浏览这些博客，对大多数人来说不现实

## 为什么不用现有平台？

| 平台 | 优势 | 局限 |
|---|---|---|
| **微信公众号** | 中文、方便 | 转述二手信息，时效差，质量参差不齐，夹带私货 |
| **InfoQ / 掘金** | 中文社区活跃 | 偏国内生态，国际大厂工程实践覆盖不足 |
| **Hacker News** | 一手、及时 | 英文、信息密度高但噪音也大，没有筛选机制 |
| **RSS 阅读器** | 自定义订阅 | 只做聚合，不做摘要和翻译，阅读负担仍在 |
| **邮件订阅（TLDR等）** | 直接送达 | 通用型，不针对你关注的特定源，且仍是英文 |

**Signal 的定位**：只关注你选定的几个高质量源，自动过滤 + AI 摘要 + 中文输出 + 邮件直达。不做大而全，做小而精。

## 为什么选邮件而不是微信/小红书/公众号？

### 1. 技术可行性（决定性因素）

| 平台 | 自动化发送 | 难度 |
|---|---|---|
| QQ 邮箱 SMTP | 原生支持，几行代码 | 极低 |
| 微信公众号 | 需要认证服务号 + 模板消息审核 | 高，有门槛 |
| 微信个人号 | 无官方 API，第三方方案不稳定 | 极高，随时失效 |
| 小红书 | 无 API，必须手动发布 | 不可能自动化 |

### 2. 内容形态

| 平台 | 适合的形态 | 周报适配度 |
|---|---|---|
| 邮件 | 长文、结构化、可带链接 | 完美匹配 |
| 微信公众号 | 长文可以，但需要排版运营 | 可行但重 |
| 小红书 | 图文短内容，1000 字以内 | 不适合 |
| 微信聊天 | 短消息 | 不适合长文 |

### 3. 可达性

- 邮件：手机、电脑、平板任何客户端都能看，不依赖特定 App
- 微信公众号：需要关注，且推送可能被折叠
- 小红书：需要打开 App 浏览

**总结**：核心原因是**自动化发送只有邮件能低成本实现**，其次是内容形态匹配。

## 为什么选这 5 个源？

| 源 | 为什么值得追 |
|---|---|
| **GitHub Blog** | 开发者平台的风向标，Copilot、Actions 等产品的第一手信息 |
| **Meta Engineering** | 大规模系统设计的教科书，分布式、AI infra 的一线实践 |
| **Netflix Tech Blog** | 流媒体、微服务、数据工程的标杆，文章深度在大厂博客中数一数二 |
| **Simon Willison** | LLM 工程实践最活跃的独立开发者，产出密度和质量都极高 |
| **The Pragmatic Engineer** | 工程文化、职业发展、行业洞察，前 Uber 工程师的一手观察 |

这 5 个源覆盖了：**平台工程 + 大规模系统 + AI 应用 + 独立视角 + 行业思考**，互补性强，重叠少。

## 技术方案

```
RSS 拉取（并行） → 过滤最近 7 天 → 存入知识库 → 注入历史趋势 → LLM 生成中文摘要 → 保存周报 → QQ 邮箱发送
```

**为什么用 RSS 而不是爬虫？**
- 5 个源全部支持原生 RSS，不需要爬取
- RSS 是结构化数据，解析稳定，不怕网站改版
- 带时间戳，天然支持按时间过滤

**为什么用 OpenAI 兼容 API？**
- 不绑定单一供应商，DeepSeek / 通义千问 / Kimi / 智谱都能用
- 切换模型只需改 `.env`，代码不用动

**为什么发邮件而不是做 App？**
- 邮件是最通用的到达方式，手机、电脑、平板都能看
- 零维护成本，不需要前端、数据库、服务器
- 周报天然适合邮件形态

## 知识积累

每次运行周报，系统会自动将文章存入本地 SQLite 数据库（`knowledge/pulse.db`），逐步构建你的技术知识库：

- **文章存储**：所有抓取的文章自动入库，按 hash 去重，不会重复存储
- **趋势追踪**：自动提取话题关键词，按周统计频率，检测上升趋势话题
- **语义搜索**：配置 embedding 模型后，支持自然语言相似度搜索（如"LLM 安全相关文章"）
- **趋势注入**：生成周报时，系统会把历史高频话题和上升趋势作为上下文注入 LLM，让摘要能参考长期趋势，避免每次都从零开始

**为什么用 SQLite + sqlite-vec？**
- 单文件存储（`knowledge/pulse.db`），零运维，手机上直接跑
- 结构化查询（按时间、来源过滤）和向量搜索（语义相似度）共用一个数据库
- sqlite-vec 是 SQLite 官方扩展，纯 C 实现，无外部依赖

**配置 embedding（可选）**：在 `.env` 中设置 `EMBEDDING_MODEL` 指向你的 API 支持的 embedding 模型名，即可启用语义搜索。不配置也不影响核心功能——文章存储、趋势分析、周报生成照常运行。

## 部署

### Android（推荐）

```bash
# 1. 安装 Termux (F-Droid 版本)
# 2. 克隆项目
git clone <repo> signal && cd signal
# 3. 一键安装
bash setup.sh
# 4. 编辑 .env 填入密钥和邮箱
vi .env
# 5. 手动测试
.venv/bin/python3 main.py
# 6. 启动定时任务
crond
```

### 任何有 Python 3.10+ 的环境

```bash
pip install -r requirements.txt
cp .env.example .env
vi .env
python3 main.py
```

## 配置

`.env` 文件：

| 变量 | 说明 | 示例 |
|---|---|---|
| `API_BASE_URL` | LLM API 地址 | `https://api.deepseek.com/v1` |
| `API_KEY` | API 密钥 | `sk-xxx` |
| `MODEL_NAME` | 模型名 | `deepseek-chat` |
| `SMTP_SENDER` | 发件 QQ 邮箱 | `123456@qq.com` |
| `SMTP_AUTH_CODE` | QQ 邮箱授权码 | 见下方说明 |
| `SMTP_RECEIVER` | 收件邮箱 | `123456@qq.com` |
| `SUMMARY_DAYS` | 回溯天数 | `7` |
| `EMBEDDING_MODEL` | embedding 模型名（启用语义搜索） | `text-embedding-v3` |

**QQ 邮箱授权码获取**：QQ 邮箱 → 设置 → 账户 → POP3/SMTP 服务 → 开启 → 生成授权码

## 添加/删除订阅源

编辑 `feeds.json`：

```json
{
  "name": "Cloudflare Blog",
  "url": "https://blog.cloudflare.com/rss/",
  "lang": "en"
}
```

加一行就是一个新源，删一行就取消订阅。

## 扩展：不止于技术周报

核心管道（RSS 拉取 → 过滤 → AI 摘要 → 邮件）是领域无关的。换一套数据源和 prompt，就能变成完全不同的周报：

| 场景 | 数据源示例 | 摘要重点 |
|---|---|---|
| **技术周报**（默认） | GitHub Blog、Meta Engineering、Netflix Tech Blog... | 技术要点、架构实践 |
| **金融投研** | Bloomberg Opinion、FT Markets、华尔街见闻... | 宏观信号、政策变化、资产影响 |
| **AI 论文** | arXiv (cs.AI/cs.CL/cs.LG)、Papers With Code... | 新架构、SOTA 突破、开源发布 |
| **行业动态** | 36氪、TechCrunch、Product Hunt... | 产品发布、融资、市场趋势 |

实现方式：通过 `--profile` 参数指定不同的配置目录，每个目录有独立的 `feeds.json` 和 `prompt.txt`：

```bash
python3 main.py --profile tech       # 技术周报
python3 main.py --profile finance    # 投研周报
python3 main.py --profile papers     # 论文周报
```

也可以设不同的发送时间：

```
0 8 * * 1   python3 main.py --profile tech       # 周一 8:00 技术
0 9 * * 1   python3 main.py --profile finance     # 周一 9:00 投研
0 8 * * 5   python3 main.py --profile papers      # 周五 8:00 论文
```

## 输出示例

邮件效果（HTML 格式，支持点击链接）：

```
Signal 周报 - 2026-05-27

## GitHub Blog（2 篇）

**Copilot Agent Mode 正式发布**
Copilot 现在支持多步骤任务编排，能够自主规划和执行开发任务...
→ 原文: https://github.blog/...

## Netflix Tech Blog（1 篇）

**Scaling ArchUnit with Nebula ArchRules**
Netflix 分享了如何在多仓库架构下规模化执行架构规则检查...
→ 原文: https://netflixtechblog.com/...

## 本周看点
GitHub 和 Netflix 本周都关注了"规模化工程治理"这个主题...
```

## 许可

MIT
