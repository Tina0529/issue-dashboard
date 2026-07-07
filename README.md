# PM Dashboard - GitHub Issue Monitor

自动监控 GitHub Projects 中的 Issue 状态，生成可视化 Dashboard。

支持 **GBase Knowledge** 和 **GBaseSupport** 两条产线，访问首页 (`public/index.html`) 会先看到入口开关，选择产线后进入各自独立的统计视图。两条产线数据分别独立抓取和存储，互不影响。

## 功能

- 每天自动更新 Issue 数据
- 按优先级 (P0/P1/P2) 分类展示
- 按截止日期预警 (已逾期、7天内)
- 按客户/标签筛选
- 按负责人分类
- 风险评分系统

## 产线结构

| 产线 | 抓取脚本 | 数据目录 | 页面目录 | 监控的 GitHub Project |
|---|---|---|---|---|
| GBaseSupport | `scripts/generate_dashboard.py` | `data/` | `public/support/` | project 16 (Support应用&功能)、project 21 (Support产品预研)、project 23 (Knowledge 应用&功能，已过期作废)、project 24 (BREAX-NEXT)、project 28 (GBaseApp) —— 与整合前完全一致，未做任何调整 |
| GBase Knowledge | `scripts/generate_knowledge_dashboard.py` | `data/knowledge/` | `public/knowledge/` | project 33 (GBase Knowledge应用&功能，`sparticleinc` org) |

`public/index.html` 是静态的入口开关页，不由脚本生成，如需调整入口文案/样式直接编辑该文件。

## 部署步骤

### 1. 创建 GitHub 仓库

```bash
# 在 GitHub 上创建新仓库，如 sparticleinc/issue-dashboard
# 然后推送本地代码
cd issue-dashboard
git init
git add .
git commit -m "Initial commit"
git remote add origin git@github.com:sparticleinc/issue-dashboard.git
git push -u origin main
```

### 2. 配置 GitHub Token

1. 进入仓库 Settings > Secrets and variables > Actions
2. 点击 "New repository secret"
3. Name: `GH_PAT`
4. Value: 你的 GitHub Personal Access Token（需要 `repo` 和 `read:project` 权限）

> ⚠️ 该 token 需要同时对 GBaseSupport 的 5 个项目和 `sparticleinc` org 的 project 33 (GBase Knowledge) 有只读访问权限。如果 token 所属账号不是 project 33 的成员/协作者，Knowledge 管线抓取会失败，需要更换有权限的账号重新生成 token。

### 3. 连接 Netlify

1. 登录 [Netlify](https://app.netlify.com)
2. 点击 "Add new site" > "Import an existing project"
3. 选择 GitHub，授权访问
4. 选择 `issue-dashboard` 仓库
5. 配置：
   - Branch: `main`
   - Publish directory: `public`
   - Build command: 留空
6. 点击 "Deploy site"

### 4. 自定义域名（可选）

1. 在 Netlify Site settings > Domain management
2. 添加自定义域名，如 `issue-dashboard.yourcompany.com`
3. 配置 DNS 记录

## 手动触发更新

在 GitHub 仓库的 Actions 页面，选择 "Update PM Dashboard" workflow，点击 "Run workflow"。

## 本地开发

```bash
# 设置环境变量
export GITHUB_TOKEN="your_token_here"

# 分别运行两条产线的生成脚本
python scripts/generate_dashboard.py            # GBaseSupport -> public/support/
python scripts/generate_knowledge_dashboard.py  # GBase Knowledge -> public/knowledge/

# 查看结果（先看入口开关页）
open public/index.html
```

## 文件结构

```
issue-dashboard/
├── .github/
│   └── workflows/
│       └── update-dashboard.yml         # GitHub Actions 定时任务（同时跑两条产线）
├── scripts/
│   ├── generate_dashboard.py            # GBaseSupport 数据获取和 HTML 生成脚本
│   └── generate_knowledge_dashboard.py  # GBase Knowledge 数据获取和 HTML 生成脚本
├── data/
│   ├── *.json                           # GBaseSupport 每日快照
│   └── knowledge/*.json                 # GBase Knowledge 每日快照
├── public/
│   ├── index.html                       # 入口开关页（静态，手写）
│   ├── support/                         # GBaseSupport Dashboard（自动更新）
│   └── knowledge/                       # GBase Knowledge Dashboard（自动更新）
├── netlify.toml                         # Netlify 配置
└── README.md
```

## 配置说明

### 修改监控的项目

- GBaseSupport：编辑 `scripts/generate_dashboard.py` 中的 `PROJECTS` 列表
- GBase Knowledge：编辑 `scripts/generate_knowledge_dashboard.py` 中的 `PROJECTS` 列表

```python
PROJECTS = [
    ("PVT_kwDOBO9uks4BDgXM", "项目名称1"),
    ("PVT_kwDOBO9uks4BHLOl", "项目名称2"),
    # 添加更多项目...
]
```

### 修改定时执行时间

编辑 `.github/workflows/update-dashboard.yml` 中的 cron 表达式：

```yaml
schedule:
  - cron: '0 1 * * *'  # UTC 01:00 = 北京时间 09:00
```

## License

MIT
